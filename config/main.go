package main

import (
	"bytes"
	"fmt"
	"io"
	"os"
	"path/filepath"

	"github.com/MoeForge/moego/json"
	"github.com/router-for-me/CLIProxyAPI/v8/internal/config"
	"github.com/router-for-me/CLIProxyAPI/v8/internal/registry"
	"golang.org/x/crypto/bcrypt"
)

func inspect() error {
	if len(os.Args) == 2 && os.Args[1] == "--models" {
		return json.NewEncoder(os.Stdout).Encode(registry.GetClaudeModels())
	}
	if len(os.Args) != 3 {
		return fmt.Errorf("arguments_invalid")
	}
	raw, err := os.ReadFile(os.Args[1])
	if err != nil {
		return err
	}
	cfg, err := config.ParseConfigBytes(raw)
	if err != nil {
		return err
	}
	key, err := io.ReadAll(io.LimitReader(os.Stdin, 65))
	if err != nil {
		return err
	}
	key = bytes.TrimSpace(key)
	if len(key) != 48 || len(cfg.APIKeys) != 1 || cfg.APIKeys[0] != string(key) || bcrypt.CompareHashAndPassword([]byte(cfg.RemoteManagement.SecretKey), key) != nil {
		return fmt.Errorf("test_management_binding_changed")
	}
	if cfg.Host != "127.0.0.1" || cfg.Port < 1 || cfg.Port > 65535 || cfg.AuthDir != filepath.Join(os.Args[2], "auth-empty") || cfg.RemoteManagement.AllowRemote || cfg.RequestLog {
		return fmt.Errorf("isolated_configuration_required")
	}
	return json.NewEncoder(os.Stdout).Encode(map[string]any{"port": cfg.Port, "logging_to_file": cfg.LoggingToFile, "refresh_workers": cfg.AuthAutoRefreshWorkers, "max_request_body_bytes": cfg.MaxRequestBodyBytes})
}

func main() {
	if err := inspect(); err != nil {
		fmt.Fprintln(os.Stderr, "saved_configuration_invalid_no_overwrite")
		os.Exit(1)
	}
}
