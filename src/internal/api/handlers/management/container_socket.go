package management

import (
	"os"
	"path/filepath"
)

// Only the service operator chooses this path; request headers cannot override it.
func (h *Handler) containerControlSocket() string {
	if p := os.Getenv("CPA_CONTAINER_SOCKET"); p != "" && filepath.IsAbs(p) {
		return filepath.Clean(p)
	}
	return filepath.Join(filepath.Dir(h.configFilePath), ".test-projects.sock")
}
