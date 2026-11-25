package executor

import "github.com/router-for-me/CLIProxyAPI/v8/internal/config"

// WithConfigSnapshot shares the native thread/tool stores while keeping this
// request's configuration immutable. It does not create a new client identity.
func (e *ClaudeExecutor) WithConfigSnapshot(cfg *config.Config) *ClaudeExecutor {
	copy := *e
	copy.cfg = cfg
	return &copy
}

// ContainerStreamResponseError retains native failure classification after the
// corresponding complete error event has already been sent to the client.
type ContainerStreamResponseError struct{ error }

func (e *ContainerStreamResponseError) Unwrap() error                   { return e.error }
func (e *ContainerStreamResponseError) UpstreamClaudeStreamError() bool { return true }
func ClaudeContainerStreamError(event []byte) error {
	var id string
	var completed bool
	var failure error
	observeClaudeSSEEvent(event, &id, &completed, &failure)
	if failure == nil {
		return nil
	}
	return &ContainerStreamResponseError{failure}
}
