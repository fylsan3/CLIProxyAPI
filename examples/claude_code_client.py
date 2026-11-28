"""Standard-library client for the separate, non-streaming Claude Code API.

No retries: a lost reply does not prove the task was never executed.
Cancellation closes this call's connection; it is not a server acknowledgement.
"""
import argparse
from concurrent.futures import CancelledError, Future
import http.client
import json
import os
import socket
import threading
from urllib.parse import urlsplit


class APIError(Exception):
    def __init__(self, status, response):
        self.status = status
        self.response = response
        super().__init__(f'CPA HTTP {status}: {response}')


class ClaudeCall:
    def __init__(self, base_url, api_key, account, prompt, model=None, timeout=7500):
        url = urlsplit(base_url)
        if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError('base_url must be an HTTP(S) URL without credentials, query or fragment')
        if not api_key or not account or not prompt:
            raise ValueError('api_key, account and prompt are required')
        connection_type = http.client.HTTPSConnection if url.scheme == 'https' else http.client.HTTPConnection
        self._connection = connection_type(url.hostname, url.port, timeout=timeout)
        self._path = url.path.rstrip('/') + '/v1/claude-code/messages'
        self._payload = {'account': account, 'prompt': prompt}
        if model is not None:
            self._payload['model'] = model
        self._key = api_key
        self._lock = threading.Lock()
        self._cancelled = threading.Event()
        self._future = Future()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        result, error = None, None
        connection = self._connection
        try:
            # Check cancellation again after connecting: cancel() may race with connect().
            if self._cancelled.is_set():
                raise CancelledError()
            connection.connect()
            if self._cancelled.is_set():
                raise CancelledError()
            connection.request('POST', self._path,
                               body=json.dumps(self._payload, ensure_ascii=False).encode('utf-8'),
                               headers={'Authorization': 'Bearer ' + self._key,
                                        'Content-Type': 'application/json', 'Connection': 'close'})
            response = connection.getresponse()
            raw = response.read()
            try:
                result = json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                raise APIError(response.status, {'error': 'response_not_json'}) from None
            if not 200 <= response.status < 300:
                raise APIError(response.status, result)
        except Exception as exc:
            error = exc
        finally:
            connection.close()
            with self._lock:
                if self._cancelled.is_set():
                    self._future.set_exception(CancelledError('HTTP connection closed; server cleanup may still be in progress'))
                elif error is not None:
                    self._future.set_exception(error)
                else:
                    self._future.set_result(result)

    def cancel(self):
        """Request cancellation by closing this call. False means already finished."""
        with self._lock:
            if self._future.done():
                return False
            self._cancelled.set()
            sock = self._connection.sock
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                sock.close()
            return True

    def result(self, timeout=None):
        """Wait for the full receipt. A local wait timeout does not cancel the call."""
        return self._future.result(timeout=timeout)


def main():
    parser = argparse.ArgumentParser(description='Call a test CPA Claude Code endpoint')
    parser.add_argument('--account', required=True, help='Account identifier shown in the Claude Code panel')
    parser.add_argument('--message', required=True)
    parser.add_argument('--model')
    parser.add_argument('--cancel-after', type=float, help='Close this request after N seconds (test only)')
    args = parser.parse_args()
    url, key = os.environ.get('CPA_URL'), os.environ.get('CPA_API_KEY')
    if not url or not key:
        parser.error('Set CPA_URL and CPA_API_KEY to your test endpoint and API key')
    if args.cancel_after is not None and args.cancel_after <= 0:
        parser.error('--cancel-after must be positive')
    call = ClaudeCall(url, key, args.account, args.message, args.model)
    timer = None
    if args.cancel_after is not None:
        timer = threading.Timer(args.cancel_after, call.cancel)
        timer.daemon = True
        timer.start()
    try:
        print(json.dumps(call.result(), ensure_ascii=False, indent=2))
    except (CancelledError, KeyboardInterrupt):
        call.cancel()
        print('已关闭本次连接并请求取消；这不是服务器清理完成的确认。')
        return 130
    except Exception as error:
        print(str(error))
        return 1
    finally:
        if timer:
            timer.cancel()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
