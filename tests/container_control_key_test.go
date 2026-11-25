package api

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestContainerControlKeyRequiresPrivateRegularFile(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "control-key")
	key := strings.Repeat("a1", 24)
	if err := os.WriteFile(path, []byte(key), 0600); err != nil {
		t.Fatal(err)
	}
	t.Setenv("CPA_LOCAL_CONTROL_KEY_FILE", path)
	if got := containerControlKey(); got != key {
		t.Fatal("private key was not accepted")
	}
	if err := os.Chmod(path, 0644); err != nil {
		t.Fatal(err)
	}
	if containerControlKey() != "" {
		t.Fatal("world-readable key accepted")
	}
	if err := os.Chmod(path, 0600); err != nil {
		t.Fatal(err)
	}
	link := filepath.Join(dir, "link")
	if err := os.Symlink(path, link); err != nil {
		t.Fatal(err)
	}
	t.Setenv("CPA_LOCAL_CONTROL_KEY_FILE", link)
	if containerControlKey() != "" {
		t.Fatal("symlink key accepted")
	}
	t.Setenv("CPA_LOCAL_CONTROL_KEY_FILE", path)
	if err := os.WriteFile(path, []byte(strings.Repeat("x", 48)), 0600); err != nil {
		t.Fatal(err)
	}
	if containerControlKey() != "" {
		t.Fatal("malformed key accepted")
	}
	t.Setenv("CPA_LOCAL_CONTROL_KEY_FILE", "relative-key")
	if containerControlKey() != "" {
		t.Fatal("relative path accepted")
	}
}
