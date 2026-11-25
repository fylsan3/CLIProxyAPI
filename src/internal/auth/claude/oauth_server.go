// Package claude provides authentication and token management functionality
// for Anthropic's Claude AI services. It handles OAuth2 token storage, serialization,
// and retrieval for maintaining authenticated sessions with the Claude API.
package claude

import (
	"context"
	"crypto/subtle"
	"errors"
	"fmt"
	"html"
	"net"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"sync"
	"time"

	log "github.com/sirupsen/logrus"
)

// OAuthServer handles the local HTTP server for OAuth callbacks.
// It listens for the authorization code response from the OAuth provider
// and captures the necessary parameters to complete the authentication flow.
type OAuthServer struct {
	// server is the underlying HTTP server instance
	server *http.Server
	// port is the port number on which the server listens
	port int
	// resultChan is a channel for sending OAuth results
	resultChan chan *OAuthResult
	// errorChan is a channel for sending OAuth errors
	errorChan chan error
	// mu is a mutex for protecting server state
	mu sync.Mutex
	// running indicates whether the server is currently running
	running       bool
	expectedState string
	completed     bool
	listener      net.Listener
}

// OAuthResult contains the result of the OAuth callback.
// It holds either the authorization code and state for successful authentication
// or an error message if the authentication failed.
type OAuthResult struct {
	// Code is the authorization code received from the OAuth provider
	Code string
	// State is the state parameter used to prevent CSRF attacks
	State string
	// Error contains any error message if the OAuth flow failed
	Error string
}

// NewOAuthServer creates a new OAuth callback server.
// It initializes the server with the specified port and creates channels
// for handling OAuth results and errors.
//
// Parameters:
//   - port: The port number on which the server should listen
//
// Returns:
//   - *OAuthServer: A new OAuthServer instance
func NewOAuthServer(port int) *OAuthServer {
	return &OAuthServer{
		port:       port,
		resultChan: make(chan *OAuthResult, 1),
		errorChan:  make(chan error, 1),
	}
}

// NewBoundOAuthServer validates callback state before consuming the pending result.
func NewBoundOAuthServer(port int, state string) (*OAuthServer, error) {
	if state == "" {
		return nil, fmt.Errorf("callback state is required")
	}
	server := NewOAuthServer(port)
	server.expectedState = state
	return server, nil
}

// Start starts the OAuth callback server.
// It sets up the HTTP handlers for the callback and success endpoints,
// and begins listening on the specified port.
//
// Returns:
//   - error: An error if the server fails to start
func (s *OAuthServer) Start() error {
	s.mu.Lock()
	defer s.mu.Unlock()

	if s.running {
		return fmt.Errorf("server is already running")
	}

	listener, err := net.Listen("tcp", fmt.Sprintf("127.0.0.1:%d", s.port))
	if err != nil {
		return fmt.Errorf("callback listener unavailable: %w", err)
	}
	s.listener = listener
	s.completed = false
	select {
	case <-s.resultChan:
	default:
	}
	select {
	case <-s.errorChan:
	default:
	}
	s.port = listener.Addr().(*net.TCPAddr).Port

	mux := http.NewServeMux()
	mux.HandleFunc("/callback", s.handleCallback)
	mux.HandleFunc("/success", s.handleSuccess)

	s.server = &http.Server{
		Addr:         listener.Addr().String(),
		Handler:      mux,
		ReadTimeout:  10 * time.Second,
		WriteTimeout: 10 * time.Second,
	}

	s.running = true

	// Start server in goroutine
	server := s.server
	go func() {
		if err := server.Serve(listener); err != nil && !errors.Is(err, http.ErrServerClosed) {
			select {
			case s.errorChan <- fmt.Errorf("server failed to start: %w", err):
			default:
			}
		}
	}()

	return nil
}

// Stop gracefully stops the OAuth callback server.
// It performs a graceful shutdown of the HTTP server with a timeout.
//
// Parameters:
//   - ctx: The context for controlling the shutdown process
//
// Returns:
//   - error: An error if the server fails to stop gracefully
func (s *OAuthServer) Stop(ctx context.Context) error {
	s.mu.Lock()
	if !s.running || s.server == nil {
		s.mu.Unlock()
		return nil
	}
	server := s.server
	s.mu.Unlock()
	// Shutdown must not hold the state lock needed by active callbacks.
	shutdownCtx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	err := server.Shutdown(shutdownCtx)
	if err != nil {
		_ = server.Close()
	}
	s.mu.Lock()
	if s.server == server {
		s.running = false
		s.server = nil
		s.listener = nil
	}
	s.mu.Unlock()
	return err
}

// WaitForCallback waits for the OAuth callback with a timeout.
// It blocks until either an OAuth result is received, an error occurs,
// or the specified timeout is reached.
//
// Parameters:
//   - timeout: The maximum time to wait for the callback
//
// Returns:
//   - *OAuthResult: The OAuth result if successful
//   - error: An error if the callback times out or an error occurs
func (s *OAuthServer) WaitForCallback(timeout time.Duration) (*OAuthResult, error) {
	select {
	case result := <-s.resultChan:
		return result, nil
	case err := <-s.errorChan:
		return nil, err
	case <-time.After(timeout):
		return nil, fmt.Errorf("timeout waiting for OAuth callback")
	}
}

// handleCallback handles the OAuth callback endpoint.
// It extracts the authorization code and state from the callback URL,
// validates the parameters, and sends the result to the waiting channel.
//
// Parameters:
//   - w: The HTTP response writer
//   - r: The HTTP request
func (s *OAuthServer) handleCallback(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("Referrer-Policy", "no-referrer")
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", 405)
		return
	}
	host, port, errHost := net.SplitHostPort(r.Host)
	if errHost != nil || port != strconv.Itoa(s.port) || (host != "localhost" && host != "127.0.0.1") {
		http.Error(w, "Invalid callback host", 400)
		return
	}
	if len(r.URL.RawQuery) > 8192 {
		http.Error(w, "Callback too large", 414)
		return
	}
	query, errQuery := url.ParseQuery(r.URL.RawQuery)
	if errQuery != nil || len(query["state"]) != 1 || len(query["code"]) > 1 || len(query["error"]) > 1 {
		http.Error(w, "Invalid callback parameters", 400)
		return
	}
	state, code, errorParam := query.Get("state"), query.Get("code"), query.Get("error")
	if state == "" || (code == "" && errorParam == "") || (code != "" && errorParam != "") {
		http.Error(w, "Invalid callback parameters", 400)
		return
	}
	s.mu.Lock()
	if s.expectedState != "" && subtle.ConstantTimeCompare([]byte(state), []byte(s.expectedState)) != 1 {
		s.mu.Unlock()
		http.Error(w, "Callback state rejected", 400)
		return
	}
	if s.completed {
		s.mu.Unlock()
		http.Error(w, "Callback already received", 409)
		return
	}
	s.completed = true
	s.sendResult(&OAuthResult{Code: code, State: state, Error: errorParam})
	s.mu.Unlock()
	if errorParam != "" {
		http.Error(w, "Authorization was not completed", 400)
		return
	}

	// Redirect to success page
	http.Redirect(w, r, "/success", http.StatusFound)
}

// handleSuccess handles the success page endpoint.
// It serves a user-friendly HTML page indicating that authentication was successful.
//
// Parameters:
//   - w: The HTTP response writer
//   - r: The HTTP request
func (s *OAuthServer) handleSuccess(w http.ResponseWriter, r *http.Request) {
	log.Debug("Serving success page")
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("Referrer-Policy", "no-referrer")

	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.WriteHeader(http.StatusOK)

	// Parse query parameters for customization
	query := r.URL.Query()
	setupRequired := query.Get("setup_required") == "true"
	platformURL := query.Get("platform_url")
	if platformURL == "" {
		platformURL = "https://console.anthropic.com/"
	}

	// Generate success page HTML with dynamic content
	successHTML := s.generateSuccessHTML(setupRequired, platformURL)

	_, err := w.Write([]byte(successHTML))
	if err != nil {
		log.Errorf("Failed to write success page: %v", err)
	}
}

// generateSuccessHTML creates the HTML content for the success page.
// It customizes the page based on whether additional setup is required
// and includes a link to the platform.
//
// Parameters:
//   - setupRequired: Whether additional setup is required after authentication
//   - platformURL: The URL to the platform for additional setup
//
// Returns:
//   - string: The HTML content for the success page
func (s *OAuthServer) generateSuccessHTML(setupRequired bool, platformURL string) string {
	page := LoginSuccessHtml
	parsed, err := url.Parse(platformURL)
	if err != nil || parsed.Scheme != "https" || parsed.Host != "console.anthropic.com" || parsed.User != nil {
		platformURL = "https://console.anthropic.com/"
	}
	platformURL = html.EscapeString(platformURL)

	// Replace platform URL placeholder
	page = strings.Replace(page, "{{PLATFORM_URL}}", platformURL, -1)

	// Add setup notice if required
	if setupRequired {
		setupNotice := strings.Replace(SetupNoticeHtml, "{{PLATFORM_URL}}", platformURL, -1)
		page = strings.Replace(page, "{{SETUP_NOTICE}}", setupNotice, 1)
	} else {
		page = strings.Replace(page, "{{SETUP_NOTICE}}", "", 1)
	}

	return page
}

// sendResult sends the OAuth result to the waiting channel.
// It ensures that the result is sent without blocking the handler.
//
// Parameters:
//   - result: The OAuth result to send
func (s *OAuthServer) sendResult(result *OAuthResult) {
	select {
	case s.resultChan <- result:
		log.Debug("OAuth result sent to channel")
	default:
		log.Warn("OAuth result channel is full, result dropped")
	}
}

// IsRunning returns whether the server is currently running.
//
// Returns:
//   - bool: True if the server is running, false otherwise
func (s *OAuthServer) IsRunning() bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.running
}
