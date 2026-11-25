package helps

import (
	"bytes"
	"context"
)

// ScanSSELineWithEnding retains the upstream line ending. ScanLines would drop
// CRLF and cause the Claude passthrough branch to silently rewrite the stream.
func ScanSSELineWithEnding(data []byte, atEOF bool) (advance int, token []byte, err error) {
	if i := bytes.IndexByte(data, '\n'); i >= 0 {
		return i + 1, data[:i+1], nil
	}
	if atEOF && len(data) > 0 {
		return len(data), data, nil
	}
	return 0, nil, nil
}

type containerResponseContextKey struct{}

func WithContainerResponseMode(ctx context.Context) context.Context {
	return context.WithValue(ctx, containerResponseContextKey{}, true)
}
func containerResponseMode(ctx context.Context) bool {
	if ctx == nil {
		return false
	}
	enabled, _ := ctx.Value(containerResponseContextKey{}).(bool)
	return enabled
}
