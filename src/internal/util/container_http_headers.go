package util

import (
	"net/http"
	"strings"
)

// Keep transport credentials and hop-local framing outside the account boundary.
// The native executor owns interpretation of all remaining request headers.
var containerRequestBlocked = map[string]bool{
	"authorization": true, "proxy-authorization": true, "x-api-key": true,
	"cookie": true, "set-cookie": true, "host": true, "content-length": true,
	"content-encoding": true, "connection": true, "keep-alive": true,
	"proxy-authenticate": true, "proxy-connection": true, "te": true,
	"trailer": true, "transfer-encoding": true, "upgrade": true,
}
var containerResponseBlocked = map[string]bool{"connection": true, "keep-alive": true, "proxy-authenticate": true, "proxy-authorization": true, "te": true, "trailer": true, "transfer-encoding": true, "upgrade": true, "set-cookie": true, "cookie": true, "authorization": true, "x-api-key": true, "content-length": true, "content-encoding": true, "access-control-allow-credentials": true, "access-control-allow-headers": true, "access-control-allow-methods": true, "access-control-allow-origin": true, "access-control-expose-headers": true, "access-control-max-age": true, "x-cpa-trace-id": true}

func containerConnectionNames(src http.Header) map[string]bool {
	result := map[string]bool{}
	for name, values := range src {
		if strings.EqualFold(name, "Connection") {
			for _, value := range values {
				for _, token := range strings.Split(value, ",") {
					result[strings.ToLower(strings.TrimSpace(token))] = true
				}
			}
		}
	}
	return result
}

// ContainerRequestHeaders preserves native executor inputs, not upstream headers.
// The native executor still decides which inputs are forwarded or regenerated.
func ContainerRequestHeaders(src http.Header) http.Header {
	dst := make(http.Header)
	scoped := containerConnectionNames(src)
	for name, values := range src {
		lower := strings.ToLower(name)
		if containerRequestBlocked[lower] || scoped[lower] || strings.HasPrefix(lower, "x-cpa-") || strings.HasPrefix(lower, "x-offline-") || strings.HasPrefix(lower, "x-test-") {
			continue
		}
		for _, value := range values {
			dst.Add(name, value)
		}
	}
	return dst
}

// ContainerResponseHeaders retains extensions and values except HTTP framing,
// credentials, local CORS/trace ownership and private control receipts.
func ContainerResponseHeaders(src http.Header) http.Header {
	dst := make(http.Header)
	scoped := containerConnectionNames(src)
	for name, values := range src {
		lower := strings.ToLower(name)
		if containerResponseBlocked[lower] || scoped[lower] || strings.HasPrefix(lower, "x-test-") || strings.HasPrefix(lower, "x-offline-") {
			continue
		}
		for _, value := range values {
			dst.Add(name, value)
		}
	}
	return dst
}
