//go:build cpa_offline

package main

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"github.com/router-for-me/CLIProxyAPI/v8/internal/accountheaders"
	"hash"
	"io"
	"net/http"
	"net/http/httptrace"
	"os"
	"path/filepath"
	"sync"
	"sync/atomic"
	"syscall"
	"time"
)

// Original HTTP data stay encrypted in the account volume. Sanitized views are
// derived separately; redaction must never destroy the original replay record.
type httpArchiveKey struct{}
type httpArchive struct {
	dir, id, kind string
	root          string
	aead          cipher.AEAD
	mu            sync.Mutex
	next          int
	failed        atomic.Bool
	finished      atomic.Int64
}

var archiveKeyMu sync.Mutex

func privateArchiveDir(path string) error {
	if err := os.MkdirAll(path, 0700); err != nil {
		return err
	}
	i, err := os.Lstat(path)
	if err != nil {
		return err
	}
	if !i.IsDir() || i.Mode()&os.ModeSymlink != 0 || i.Mode().Perm() != 0700 {
		return errors.New("archive_directory_not_private")
	}
	return nil
}
func captureStorageAvailable(path string) bool {
	var info syscall.Statfs_t
	return syscall.Statfs(path, &info) == nil && uint64(info.Bavail)*uint64(info.Bsize) > 512*1024*1024
}
func newHTTPArchive(root, kind string) (*httpArchive, error) {
	if !captureStorageAvailable(root) {
		return nil, errors.New("capture_storage_reserve")
	}

	archiveKeyMu.Lock()
	defer archiveKeyMu.Unlock()
	keyPath := filepath.Join(root, "http-capture.key")
	if err := safeFile(keyPath); os.IsNotExist(err) {
		key := make([]byte, 32)
		if _, err = rand.Read(key); err != nil {
			return nil, err
		}
		if err = durableWrite(keyPath, key); err != nil {
			return nil, err
		}
	} else if err != nil {
		return nil, err
	}
	key, err := os.ReadFile(keyPath)
	if err != nil {
		return nil, err
	}
	block, err := aes.NewCipher(key)
	if err != nil {
		return nil, err
	}
	aead, err := cipher.NewGCM(block)
	if err != nil {
		return nil, err
	}
	base := filepath.Join(root, "http-samples")
	if err = privateArchiveDir(base); err != nil {
		return nil, err
	}
	id := make([]byte, 12)
	if _, err = rand.Read(id); err != nil {
		return nil, err
	}
	s := &httpArchive{root: root, id: hex.EncodeToString(id), kind: kind, aead: aead}
	s.dir = filepath.Join(base, s.id)
	if err = os.Mkdir(s.dir, 0700); err != nil {
		return nil, err
	}
	if err = durableWrite(filepath.Join(s.dir, "sample.json"), mustArchiveJSON(map[string]any{"schema": 1, "id": s.id, "kind": kind, "created_at": time.Now().UTC(), "encrypted": true, "boundary": "final_http_transport", "tls_packets_preserved": false})); err != nil {
		return nil, err
	}
	return s, nil
}
func mustArchiveJSON(v any) []byte { b, _ := json.Marshal(v); return b }
func (s *httpArchive) status() map[string]any {
	s.mu.Lock()
	n := s.next
	s.mu.Unlock()
	state := "complete"
	if s.failed.Load() || n == 0 || int64(n) != s.finished.Load() {
		state = "incomplete"
	}
	return map[string]any{"id": s.id, "state": state, "exchanges": n, "encrypted": true}
}

// Each record is independently authenticated, with an authenticated empty final
// record. Missing/truncated chunks cannot be mistaken for a complete file.
type archiveFile struct {
	f       *os.File
	aead    cipher.AEAD
	aad     []byte
	err     error
	written int64
}

func (s *httpArchive) file(path string) *archiveFile {
	f, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	w := &archiveFile{f: f, aead: s.aead, aad: []byte(filepath.Base(path)), err: err}
	if err == nil {
		_, w.err = f.Write([]byte("CPAENC1\n"))
	}
	return w
}
func (w *archiveFile) chunk(p []byte) {
	if w.err != nil {
		return
	}
	if w.f != nil && w.written/(1024*1024) != (w.written+int64(len(p)))/(1024*1024) && !captureStorageAvailable(filepath.Dir(w.f.Name())) {
		w.err = errors.New("capture_storage_reserve")
		return
	}
	w.written += int64(len(p))
	nonce := make([]byte, w.aead.NonceSize())
	if _, w.err = rand.Read(nonce); w.err != nil {
		return
	}
	sealed := w.aead.Seal(nonce, nonce, p, w.aad)
	var size [4]byte
	binary.BigEndian.PutUint32(size[:], uint32(len(sealed)))
	if _, w.err = w.f.Write(size[:]); w.err == nil {
		_, w.err = w.f.Write(sealed)
	}
}
func (w *archiveFile) Write(p []byte) (int, error) {
	n := len(p)
	for len(p) > 0 {
		end := min(len(p), 65536)
		w.chunk(p[:end])
		p = p[end:]
	}
	if w.err != nil {
		return 0, w.err
	}
	return n, nil
}
func (w *archiveFile) close() error {
	w.chunk(nil)
	if w.f != nil {
		if err := w.f.Sync(); w.err == nil {
			w.err = err
		}
		if err := w.f.Close(); w.err == nil {
			w.err = err
		}
	}
	return w.err
}
func (s *httpArchive) record(path string, v any) bool {
	tmp := path + ".tmp"
	w := s.file(tmp)
	// Bind ciphertext to the stable filename, not its atomic-write temporary name.
	w.aad = []byte(filepath.Base(path))
	_, _ = w.Write(mustArchiveJSON(v))
	err := w.close()
	if err == nil {
		err = os.Rename(tmp, path)
	}
	if err == nil {
		var d *os.File
		d, err = os.Open(filepath.Dir(path))
		if err == nil {
			err = d.Sync()
			d.Close()
		}
	}
	if err != nil {
		s.failed.Store(true)
		_ = os.Remove(tmp)
		return false
	}
	return true
}

type archiveBody struct {
	io.ReadCloser
	file     *archiveFile
	digest   hash.Hash
	bytes    int64
	expected int64
	once     sync.Once
	done     func(int64, string, bool)
}

func (b *archiveBody) finish(complete bool) {
	b.once.Do(func() {
		err := b.file.close()
		b.done(b.bytes, hex.EncodeToString(b.digest.Sum(nil)), complete && err == nil)
	})
}
func (b *archiveBody) Read(p []byte) (int, error) {
	n, err := b.ReadCloser.Read(p)
	if n > 0 {
		b.bytes += int64(n)
		b.digest.Write(p[:n])
		_, _ = b.file.Write(p[:n])
	}
	if err != nil {
		b.finish(err == io.EOF && (b.expected < 0 || b.bytes == b.expected))
	}
	return n, err
}
func (b *archiveBody) Close() error {
	err := b.ReadCloser.Close()
	b.finish(err == nil && b.expected >= 0 && b.bytes == b.expected)
	return err
}

func (s *httpArchive) send(original *http.Request, next func(*http.Request) (*http.Response, error)) (*http.Response, error) {
	return s.sendCompared(original, nil, next)
}

// before is the executor input immediately before the unified final policy,
// not the customer/NewAPI ingress. Both snapshots remain encrypted.
func (s *httpArchive) sendCompared(original, before *http.Request, next func(*http.Request) (*http.Response, error)) (*http.Response, error) {
	s.mu.Lock()
	s.next++
	number := s.next
	s.mu.Unlock()
	name := hex.EncodeToString([]byte{byte(number >> 8), byte(number)})
	dir := filepath.Join(s.dir, name)
	if err := os.Mkdir(dir, 0700); err != nil {
		s.failed.Store(true)
		return next(original)
	}
	var mu sync.Mutex
	meta := map[string]any{"archive_id": s.id, "exchange": name, "kind": s.kind, "method": original.Method, "url": original.URL.String(), "host": original.Host, "headers": original.Header.Clone(), "content_length": original.ContentLength, "transfer_encoding": original.TransferEncoding, "close": original.Close, "captured_at": time.Now().UTC(), "policy_version": accountheaders.Version(), "policy_sha256": accountheaders.Digest(), "complete": false}
	if before != nil {
		meta["before_override"] = map[string]any{"headers": before.Header.Clone(), "close": before.Close, "boundary": "executor_before_final_header_policy"}
	}
	wire := []map[string]any{}
	writes := 0
	writeRequest := func() { meta["wire_headers"] = wire; s.record(filepath.Join(dir, "request.json.enc"), meta) }
	trace := &httptrace.ClientTrace{
		WroteHeaderField: func(key string, values []string) {
			mu.Lock()
			defer mu.Unlock()
			wire = append(wire, map[string]any{"name": key, "values": append([]string(nil), values...)})
			if http.CanonicalHeaderKey(key) == "Transfer-Encoding" {
				meta["transfer_encoding"] = append([]string(nil), values...)
			}
		},
		WroteRequest: func(info httptrace.WroteRequestInfo) {
			mu.Lock()
			defer mu.Unlock()
			writes++
			meta["write_attempts"] = writes
			meta["write_succeeded"] = info.Err == nil
			recordHeaderAudit(s.root, s.id, original.URL.Path, wire, info.Err == nil)
			if writes > 1 {
				s.failed.Store(true)
			}
			writeRequest()
		},
	}
	req := original.Clone(httptrace.WithClientTrace(original.Context(), trace))
	requestFile := s.file(filepath.Join(dir, "request.bin.enc"))
	if req.Body == nil || req.Body == http.NoBody {
		empty := sha256.Sum256(nil)
		meta["bytes"] = 0
		meta["sha256"] = hex.EncodeToString(empty[:])
		meta["complete"] = requestFile.close() == nil
	} else {
		expected := req.ContentLength
		if expected == 0 {
			expected = -1
		}
		req.Body = &archiveBody{ReadCloser: req.Body, file: requestFile, digest: sha256.New(), expected: expected, done: func(n int64, sum string, complete bool) {
			mu.Lock()
			defer mu.Unlock()
			meta["bytes"] = n
			meta["sha256"] = sum
			meta["complete"] = complete
			meta["trailers"] = original.Trailer.Clone()
			if !complete {
				recordCaptureIssue(s.root, "request_capture_incomplete")
				s.failed.Store(true)
			}
			writeRequest()
		}}
	}
	mu.Lock()
	writeRequest()
	mu.Unlock()
	res, err := next(req)
	mu.Lock()
	writeRequest()
	mu.Unlock()
	if err != nil || res == nil {
		s.failed.Store(true)
		s.record(filepath.Join(dir, "response.json.enc"), map[string]any{"complete": false, "transport_error": true})
		return res, err
	}
	record := map[string]any{"archive_id": s.id, "exchange": name, "status": res.StatusCode, "status_text": res.Status, "protocol": res.Proto, "headers": res.Header.Clone(), "content_length": res.ContentLength, "transfer_encoding": res.TransferEncoding, "uncompressed_by_transport": res.Uncompressed, "complete": false}
	s.record(filepath.Join(dir, "response.json.enc"), record)
	if res.Uncompressed {
		s.failed.Store(true)
	}
	done := func(n int64, sum string, complete bool) {
		record["bytes"] = n
		record["sha256"] = sum
		record["complete"] = complete
		record["trailers"] = res.Trailer.Clone()
		if !complete {
			recordCaptureIssue(s.root, "response_capture_incomplete")
			s.failed.Store(true)
		}
		s.record(filepath.Join(dir, "response.json.enc"), record)
		mu.Lock()
		requestComplete := meta["complete"] == true && meta["write_succeeded"] == true && len(wire) > 0
		mu.Unlock()
		if !requestComplete {
			s.failed.Store(true)
		}
		s.finished.Add(1)
	}
	responseFile := s.file(filepath.Join(dir, "response.bin.enc"))
	if res.Body == nil {
		empty := sha256.Sum256(nil)
		done(0, hex.EncodeToString(empty[:]), responseFile.close() == nil)
	} else {
		res.Body = &archiveBody{ReadCloser: res.Body, file: responseFile, digest: sha256.New(), expected: res.ContentLength, done: done}
	}
	return res, nil
}
