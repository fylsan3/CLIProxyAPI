//go:build cpa_offline

package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"hash"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"sync"
	"time"
)

// Arming is a local administrative operation, never a client-controlled header.
// Only one matching model input is captured; OAuth and unrelated traffic are excluded.
type modelSampleKey struct{}
type modelSample struct {
	mu   sync.Mutex
	dir  string
	next int
}
type modelSampleArm struct {
	InputSHA256 string `json:"input_sha256"`
	Expires     int64  `json:"expires"`
	ID          string `json:"id"`
}

var sampleIDPattern = regexp.MustCompile(`^[0-9a-f]{24}$`)

func claimModelSample(root string, raw []byte, run, attempt string) *modelSample {
	path := filepath.Join(root, "model-sample-arm.json")
	info, err := os.Lstat(path)
	if err != nil || !info.Mode().IsRegular() || info.Mode().Perm()&0077 != 0 || info.Size() > 4096 {
		return nil
	}
	b, err := os.ReadFile(path)
	if err != nil {
		return nil
	}
	var arm modelSampleArm
	if json.Unmarshal(b, &arm) != nil || !sampleIDPattern.MatchString(arm.ID) || arm.Expires < time.Now().Unix() || arm.Expires > time.Now().Add(time.Hour).Unix() {
		return nil
	}
	digest := sha256.Sum256(raw)
	if hex.EncodeToString(digest[:]) != arm.InputSHA256 {
		return nil
	}
	claimed := path + ".claimed-" + arm.ID
	if os.Rename(path, claimed) != nil {
		return nil
	}
	defer os.Remove(claimed)
	base := filepath.Join(root, "model-samples")
	if os.MkdirAll(base, 0700) != nil {
		return nil
	}
	info, err = os.Lstat(base)
	if err != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 || info.Mode().Perm()&0077 != 0 {
		return nil
	}
	dir := filepath.Join(base, arm.ID)
	if os.Mkdir(dir, 0700) != nil {
		return nil
	}
	sampleJSON(filepath.Join(dir, "sample.json"), map[string]any{"schema": 1, "source": "worker_final_transport", "id": arm.ID, "run": run, "attempt": attempt, "input_sha256": arm.InputSHA256, "created_at": time.Now().UTC(), "completion_record": "each exchange response.json"})
	return &modelSample{dir: dir}
}
func sampleJSON(path string, value any) {
	raw, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		return
	}
	tmp := path + ".tmp"
	f, err := os.OpenFile(tmp, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil {
		return
	}
	_, err = f.Write(raw)
	if err == nil {
		err = f.Sync()
	}
	f.Close()
	if err == nil {
		os.Rename(tmp, path)
	} else {
		os.Remove(tmp)
	}
}
func sampleHeaders(h http.Header) http.Header {
	out := h.Clone()
	for k := range out {
		switch http.CanonicalHeaderKey(k) {
		case "Authorization", "Proxy-Authorization", "X-Api-Key", "Cookie", "Set-Cookie":
			delete(out, k)
		}
	}
	return out
}

type sampleBody struct {
	io.ReadCloser
	file   *os.File
	digest hash.Hash
	count  int64
	once   sync.Once
	failed bool
	done   func(int64, string, bool)
}

func (b *sampleBody) finish(complete bool) {
	b.once.Do(func() {
		if b.file != nil {
			if b.file.Sync() != nil {
				b.failed = true
			}
			if b.file.Close() != nil {
				b.failed = true
			}
		}
		b.done(b.count, hex.EncodeToString(b.digest.Sum(nil)), complete && !b.failed)
	})
}
func (b *sampleBody) Read(p []byte) (int, error) {
	n, err := b.ReadCloser.Read(p)
	if n > 0 {
		b.digest.Write(p[:n])
		b.count += int64(n)
		if b.file != nil {
			if _, e := b.file.Write(p[:n]); e != nil {
				b.failed = true
			}
		} else {
			b.failed = true
		}
	}
	if err != nil {
		b.finish(err == io.EOF)
	}
	return n, err
}
func (b *sampleBody) Close() error { err := b.ReadCloser.Close(); b.finish(false); return err }
func (s *modelSample) send(req *http.Request, next func(*http.Request) (*http.Response, error)) (*http.Response, error) {
	s.mu.Lock()
	s.next++
	index := s.next
	s.mu.Unlock()
	dir := filepath.Join(s.dir, time.Now().UTC().Format("150405.000000000")+"-"+hex.EncodeToString([]byte{byte(index >> 8), byte(index)}))
	if os.Mkdir(dir, 0700) != nil {
		return next(req)
	}
	meta := map[string]any{"method": req.Method, "host": req.URL.Host, "path": req.URL.EscapedPath(), "query": req.URL.RawQuery, "headers": sampleHeaders(req.Header), "content_length": req.ContentLength, "captured_at": time.Now().UTC(), "complete": false}
	// Use a duplicate body when available; never consume the live request for logging.
	if req.GetBody != nil {
		copy, err := req.GetBody()
		if err == nil {
			f, e := os.OpenFile(filepath.Join(dir, "request.bin"), os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
			if e == nil {
				h := sha256.New()
				n, e := io.Copy(io.MultiWriter(f, h), copy)
				syncErr := f.Sync()
				f.Close()
				meta["complete"] = e == nil && syncErr == nil
				meta["bytes"] = n
				meta["sha256"] = hex.EncodeToString(h.Sum(nil))
			}
			copy.Close()
		}
	}
	sampleJSON(filepath.Join(dir, "request.json"), meta)
	res, err := next(req)
	if err != nil {
		sampleJSON(filepath.Join(dir, "response.json"), map[string]any{"complete": false, "transport_error": true})
		return res, err
	}
	if res == nil {
		return res, err
	}
	record := map[string]any{"status": res.StatusCode, "headers": sampleHeaders(res.Header), "complete": false, "content_length": res.ContentLength}
	sampleJSON(filepath.Join(dir, "response.json"), record)
	if res.Body != nil {
		f, _ := os.OpenFile(filepath.Join(dir, "response.bin"), os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
		res.Body = &sampleBody{ReadCloser: res.Body, file: f, digest: sha256.New(), done: func(n int64, hash string, complete bool) {
			record["bytes"] = n
			record["sha256"] = hash
			record["complete"] = complete
			sampleJSON(filepath.Join(dir, "response.json"), record)
		}}
	}
	return res, err
}
