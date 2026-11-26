package main

// Exercise the real archive implementation against a loopback HTTP fixture.
// This measures the capture boundary, not model latency or fleet capacity.
import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"sync"
	"sync/atomic"
	"syscall"
	"testing"
	"time"
)

type discardResponse struct{ header http.Header }

func (w *discardResponse) Header() http.Header         { return w.header }
func (w *discardResponse) WriteHeader(int)             {}
func (w *discardResponse) Write(p []byte) (int, error) { return len(p), nil }
func (w *discardResponse) Flush()                      {}

type performanceCase struct {
	Name                      string
	Request, Response, Chunks int
}
type performanceRow struct {
	Case        string  `json:"case"`
	Enabled     bool    `json:"capture_enabled"`
	Concurrency int     `json:"concurrency"`
	Count       int     `json:"requests"`
	P50         float64 `json:"p50_ms"`
	P95         float64 `json:"p95_ms"`
	Throughput  float64 `json:"requests_per_second"`
	Allocated   float64 `json:"allocated_bytes_per_request"`
	PeakHeap    uint64  `json:"sampled_peak_heap_bytes"`
	Logical     float64 `json:"archive_logical_bytes_per_request"`
	Physical    float64 `json:"archive_allocated_bytes_per_request"`
}

func directoryBytes(root string) (int64, int64, error) {
	var logical, physical int64
	err := filepath.Walk(root, func(_ string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		if !info.IsDir() {
			logical += info.Size()
			physical += info.Sys().(*syscall.Stat_t).Blocks * 512
		}
		return nil
	})
	return logical, physical, err
}

func TestArchivePerformance(t *testing.T) {
	base := os.Getenv("BENCH_DIR")
	if base == "" {
		t.Fatal("BENCH_DIR required")
	}
	root, err := os.MkdirTemp(base, "capture-performance-")
	if err != nil {
		t.Fatal(err)
	}
	defer os.RemoveAll(root)
	cases := []performanceCase{{"small", 4 << 10, 4 << 10, 1}, {"context160k", 160 << 10, 32 << 10, 1}, {"large_reply", 160 << 10, 512 << 10, 1}, {"stream64", 160 << 10, 256 << 10, 64}}
	rows := []performanceRow{}
	for _, c := range cases {
		request := append([]byte(`{"messages":[{"role":"user","content":"`), bytes.Repeat([]byte("x"), c.Request)...)
		request = append(request, []byte(`"}]}`)...)
		response := bytes.Repeat([]byte("y"), c.Response)
		want := sha256.Sum256(response)
		srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			b, e := io.ReadAll(r.Body)
			if e != nil || !bytes.Equal(b, request) {
				t.Error("fixture request changed", e)
				w.WriteHeader(400)
				return
			}
			if c.Chunks > 1 {
				w.Header().Set("Content-Type", "text/event-stream")
				w.Header().Set("Trailer", "X-End")
			}
			for i := 0; i < c.Chunks; i++ {
				if _, e = w.Write(response[i*c.Response/c.Chunks : (i+1)*c.Response/c.Chunks]); e != nil {
					return
				}
				if c.Chunks > 1 {
					w.(http.Flusher).Flush()
				}
			}
			if c.Chunks > 1 {
				w.Header().Set("X-End", "complete")
			}
		}))
		transport := http.DefaultTransport.(*http.Transport).Clone()
		transport.DisableCompression = true
		transport.MaxIdleConnsPerHost = 8
		for _, concurrency := range []int{1, 4} {
			type aggregate struct {
				durations         []float64
				elapsed           time.Duration
				allocated         uint64
				heap              uint64
				logical, physical int64
			}
			totals := map[bool]*aggregate{false: {}, true: {}}
			// ABBA BAAB order reduces a one-direction warm-cache/order bias.
			for phase, enabled := range []bool{false, true, true, false, true, false, false, true} {
				phaseRoot := filepath.Join(root, fmt.Sprintf("%s-%d-%d", c.Name, concurrency, phase))
				if e := os.Mkdir(phaseRoot, 0700); e != nil {
					t.Fatal(e)
				}
				one := func() error {
					req, e := http.NewRequestWithContext(context.Background(), "POST", srv.URL+"/v1/messages", bytes.NewReader(request))
					if e != nil {
						return e
					}
					for k, v := range modelHeaderOverrides() {
						req.Header.Set(k, v)
					}
					var a *httpArchive
					var res *http.Response
					if enabled {
						a, e = newHTTPArchive(phaseRoot, "benchmark")
						if e != nil {
							return e
						}
						a.snapshot(filepath.Join(a.dir, "ingress.json.enc"), "worker_ingress", request, req.Header, nil)
						res, e = a.sendCompared(req, req.Clone(req.Context()), transport.RoundTrip)
					} else {
						res, e = transport.RoundTrip(req)
					}
					if e != nil {
						return e
					}
					h := sha256.New()
					var out io.Writer = &discardResponse{header: http.Header{}}
					var observer *archiveResponseWriter
					if enabled {
						observer = &archiveResponseWriter{ResponseWriter: out.(*discardResponse), archive: a, digest: sha256.New()}
						out = observer
					}
					_, e = io.Copy(io.MultiWriter(out, h), res.Body)
					closeErr := res.Body.Close()
					if observer != nil {
						observer.finish(req.Context(), e == nil)
					}
					if e != nil {
						return e
					}
					if closeErr != nil {
						return closeErr
					}
					if !bytes.Equal(h.Sum(nil), want[:]) || res.StatusCode != 200 {
						return fmt.Errorf("response changed")
					}
					if enabled && a.status()["state"] != "complete" {
						return fmt.Errorf("incomplete archive: %v", a.status())
					}
					return nil
				}
				// Warm transport, key, encoding metadata; warm-up storage is excluded below.
				if e := one(); e != nil {
					t.Fatal(e)
				}
				l0, p0, e := directoryBytes(phaseRoot)
				if e != nil {
					t.Fatal(e)
				}
				runtime.GC()
				var before, after runtime.MemStats
				runtime.ReadMemStats(&before)
				var peak atomic.Uint64
				peak.Store(before.HeapAlloc)
				done := make(chan struct{})
				sampleDone := make(chan struct{})
				go func() {
					defer close(sampleDone)
					ticker := time.NewTicker(time.Millisecond)
					defer ticker.Stop()
					for {
						select {
						case <-done:
							return
						case <-ticker.C:
							var m runtime.MemStats
							runtime.ReadMemStats(&m)
							for old := peak.Load(); m.HeapAlloc > old; old = peak.Load() {
								if peak.CompareAndSwap(old, m.HeapAlloc) {
									break
								}
							}
						}
					}
				}()
				const perWorker = 3
				times := make(chan float64, concurrency*perWorker)
				errs := make(chan error, concurrency*perWorker)
				var wg sync.WaitGroup
				start := time.Now()
				for j := 0; j < concurrency; j++ {
					wg.Add(1)
					go func() {
						defer wg.Done()
						for k := 0; k < perWorker; k++ {
							s := time.Now()
							e := one()
							times <- float64(time.Since(s)) / float64(time.Millisecond)
							if e != nil {
								errs <- e
							}
						}
					}()
				}
				wg.Wait()
				elapsed := time.Since(start)
				close(done)
				<-sampleDone
				runtime.ReadMemStats(&after)
				close(times)
				close(errs)
				for e := range errs {
					t.Fatal(e)
				}
				l1, p1, e := directoryBytes(phaseRoot)
				if e != nil {
					t.Fatal(e)
				}
				a := totals[enabled]
				for v := range times {
					a.durations = append(a.durations, v)
				}
				a.elapsed += elapsed
				a.allocated += after.TotalAlloc - before.TotalAlloc
				if peak.Load() > a.heap {
					a.heap = peak.Load()
				}
				a.logical += l1 - l0
				a.physical += p1 - p0
				if e := os.RemoveAll(phaseRoot); e != nil {
					t.Fatal(e)
				}
			}
			for _, enabled := range []bool{false, true} {
				a := totals[enabled]
				sort.Float64s(a.durations)
				n := len(a.durations)
				rows = append(rows, performanceRow{c.Name, enabled, concurrency, n, a.durations[(n-1)/2], a.durations[int(float64(n-1)*0.95)], float64(n) / a.elapsed.Seconds(), float64(a.allocated) / float64(n), a.heap, float64(a.logical) / float64(n), float64(a.physical) / float64(n)})
			}
		}
		transport.CloseIdleConnections()
		srv.Close()
	}
	output := map[string]any{"scope": "real archive boundary plus loopback fixture; not full CPA service", "go": runtime.Version(), "os": runtime.GOOS, "arch": runtime.GOARCH, "gomaxprocs": runtime.GOMAXPROCS(0), "memory_note": "heap includes fixture and benchmark; allocation is cumulative, not retained RSS; 1ms peak sampling can miss bursts", "rows": rows}
	raw, e := json.Marshal(output)
	if e != nil {
		t.Fatal(e)
	}
	fmt.Printf("BENCH_RESULT=%s\n", raw)
}
