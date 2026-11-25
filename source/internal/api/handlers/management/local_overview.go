package management

import (
	"encoding/json"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/router-for-me/CLIProxyAPI/v8/internal/buildinfo"
)

type workloadRow struct {
	Name  string `json:"name"`
	State string `json:"state"`
}
type workloadSnapshot struct {
	Source   string        `json:"source"`
	Observed time.Time     `json:"observed"`
	Rows     []workloadRow `json:"rows"`
}

func readWorkloadSnapshot(dir string, now time.Time) (string, []workloadRow) {
	path := filepath.Join(dir, "local-workloads.json")
	info, err := os.Lstat(path)
	if os.IsNotExist(err) {
		return "unconfigured", nil
	}
	if err != nil || !info.Mode().IsRegular() || info.Size() > 65536 || info.Mode().Perm()&0022 != 0 {
		return "unavailable", nil
	}
	b, err := os.ReadFile(path)
	var snap workloadSnapshot
	if err != nil || json.Unmarshal(b, &snap) != nil || snap.Observed.IsZero() || len(snap.Rows) > 512 {
		return "unavailable", nil
	}
	age := now.Sub(snap.Observed)
	if age < -5*time.Second || age > 45*time.Second {
		return "stale", nil
	}
	if snap.Source == "unconfigured" || snap.Source == "unavailable" {
		return snap.Source, nil
	}
	if snap.Source != "observed" {
		return "unavailable", nil
	}
	for i, row := range snap.Rows {
		if len(row.Name) == 0 || len(row.Name) > 128 {
			return "unavailable", nil
		}
		switch row.State {
		case "running", "exited", "paused", "created", "restarting", "dead", "removing":
		default:
			snap.Rows[i].State = "unknown"
		}
	}
	sort.Slice(snap.Rows, func(i, j int) bool { return snap.Rows[i].Name < snap.Rows[j].Name })
	return "observed", snap.Rows
}

type progressRow struct {
	Provider string    `json:"provider"`
	Account  string    `json:"account,omitempty"`
	Stage    string    `json:"stage"`
	Started  time.Time `json:"started"`
}

func (s *oauthSessionStore) noteSavedForOverview(state, name string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if v, ok := s.sessions[state]; ok && name != "" {
		v.overviewSavedName = filepath.Base(name)
		s.sessions[state] = v
	}
}

func (s *oauthSessionStore) overview(now time.Time) []progressRow {
	s.mu.RLock()
	defer s.mu.RUnlock()
	rows := make([]progressRow, 0, len(s.sessions))
	for _, v := range s.sessions {
		if !v.ExpiresAt.After(now) {
			continue
		}
		row := progressRow{Provider: v.Provider, Started: v.CreatedAt, Stage: "waiting"}
		if v.Completed {
			row.Account = v.overviewSavedName
		}
		if v.Completed && v.AuthID != "" {
			row.Account = filepath.Base(v.AuthID)
		}
		if v.Target != nil && v.Target.FileName != "" {
			row.Account = filepath.Base(v.Target.FileName)
		}
		switch {
		case v.Status != "" || v.AdoptError != "" || v.VerifyError != "":
			row.Stage = "failed"
		case v.Completed && (v.Saved || v.Adopted || v.overviewSavedName != ""):
			row.Stage = "completed"
		case v.Completed:
			row.Stage = "ended"
		case v.Committing || v.SIWCCommitting:
			row.Stage = "processing"
		}
		rows = append(rows, row)
	}
	sort.Slice(rows, func(i, j int) bool { return rows[i].Started.Before(rows[j].Started) })
	return rows
}
func (h *Handler) LocalOverview(c *gin.Context) {
	c.Header("Cache-Control", "no-store")
	accounts := make([]gin.H, 0)
	if h.authManager == nil {
		c.Status(503)
		return
	}
	for _, a := range h.authManager.List() {
		if !isAuthFileListable(a) {
			continue
		}
		name := a.FileName
		if name == "" {
			name = a.Label
		}
		if name == "" {
			name = a.Provider
		}
		status := string(a.Status)
		if a.Disabled {
			status = "disabled"
		} else if a.Unavailable && status == "active" {
			status = "unavailable"
		}
		accounts = append(accounts, gin.H{"name": filepath.Base(name), "provider": a.Provider, "status": status})
	}
	sort.SliceStable(accounts, func(i, j int) bool {
		return strings.Compare(accounts[i]["name"].(string), accounts[j]["name"].(string)) < 0
	})
	now := time.Now().UTC()
	scope, rows := readWorkloadSnapshot(filepath.Dir(h.configFilePath), now)
	c.JSON(200, gin.H{"version": buildinfo.Version, "observed": now, "accounts": accounts, "progress": oauthSessions.overview(now), "runtime": gin.H{"source": scope, "rows": rows}})
}
