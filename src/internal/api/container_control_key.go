package api

import (
	"os"
	"path/filepath"
	"strings"
)

// containerControlKey uses the existing localhost-only management password path.
// It does not enable the TUI keep-alive endpoint or remote management access.
func containerControlKey() string {
	path := os.Getenv("CPA_LOCAL_CONTROL_KEY_FILE")
	if path == "" || !filepath.IsAbs(path) {
		return ""
	}
	info, err := os.Lstat(path)
	if err != nil || !info.Mode().IsRegular() || info.Mode().Perm() != 0600 || info.Size() != 48 {
		return ""
	}
	raw, err := os.ReadFile(path)
	if err != nil || len(raw) != 48 {
		return ""
	}
	key := string(raw)
	if strings.IndexFunc(key, func(r rune) bool { return !(r >= '0' && r <= '9' || r >= 'a' && r <= 'f') }) >= 0 {
		return ""
	}
	return key
}
