package util

import (
	"bytes"
	"errors"
	"io"

	"github.com/MoeForge/moego/base64"
	"github.com/MoeForge/moego/json"
	"github.com/router-for-me/CLIProxyAPI/v8/internal/config"
)

const ContainerConfigHeader = "X-Offline-Execution-Config"

// ContainerExecutionConfig contains no credentials, proxy or client identity fields.
// Scheduling and retries remain central; only execution settings cross this boundary.
type ContainerExecutionConfig struct {
	Version           int                             `json:"version"`
	ModelLevelCooling bool                            `json:"model_level_cooling"`
	DisableCooling    bool                            `json:"disable_cooling"`
	Payload           config.PayloadConfig            `json:"payload"`
	ErrorRules        []config.RequestScopedErrorRule `json:"error_rules,omitempty"`
}

func ContainerConfigSnapshot(cfg *config.Config) ContainerExecutionConfig {
	c := ContainerExecutionConfig{Version: 1}
	if cfg != nil {
		snapshot := cfg.CloneForRuntime()
		c.ModelLevelCooling = snapshot.Claude.ModelLevelCooling
		c.DisableCooling = snapshot.DisableCooling
		c.Payload = snapshot.Payload
		c.ErrorRules = snapshot.OAuthRequestScopedErrors["claude"]
	}
	return c
}

func EncodeContainerConfig(c ContainerExecutionConfig) (string, error) {
	b, err := json.Marshal(c)
	if err != nil {
		return "", err
	}
	if len(b) > 32768 {
		return "", errors.New("container_execution_config_too_large")
	}
	return base64.RawURLEncoding.EncodeToString(b), nil
}

func DecodeContainerConfig(value string) (*config.Config, error) {
	if len(value) > 44000 {
		return nil, errors.New("container_execution_config_too_large")
	}
	c := ContainerExecutionConfig{Version: 1}
	if value != "" {
		b, err := base64.RawURLEncoding.DecodeString(value)
		if err != nil {
			return nil, errors.New("invalid_container_execution_config")
		}
		d := json.NewDecoder(bytes.NewReader(b))
		d.DisallowUnknownFields()
		if err = d.Decode(&c); err != nil {
			return nil, errors.New("invalid_container_execution_config")
		}
		var extra any
		if d.Decode(&extra) != io.EOF {
			return nil, errors.New("invalid_container_execution_config")
		}
	}
	if c.Version != 1 {
		return nil, errors.New("unsupported_container_execution_config")
	}
	cfg := &config.Config{DisableClaudeCloakMode: true, DisableCooling: c.DisableCooling, Payload: c.Payload}
	cfg.Claude.ModelLevelCooling = c.ModelLevelCooling
	cfg.OAuthRequestScopedErrors = map[string][]config.RequestScopedErrorRule{"claude": c.ErrorRules}
	return cfg, nil
}
