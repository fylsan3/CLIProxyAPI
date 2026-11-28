"""Local loopback only: sample client receipts, errors and connection cancellation."""
import http.server
import json
import select
import sys
import threading
import unittest
from concurrent.futures import CancelledError
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'examples'))
from claude_code_client import ClaudeCall, APIError


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.observed = []
        self.arrived = threading.Event()
        self.disconnected = threading.Event()
        parent = self
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                value = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                parent.observed.append((self.path, self.headers['Authorization'], value))
                if value['prompt'] == 'wait':
                    parent.arrived.set()
                    ready, _, _ = select.select([self.connection], [], [], 5)
                    if ready and self.connection.recv(1) == b'':
                        parent.disconnected.set()
                    return
                status = 409 if value['prompt'] == 'busy' else 200
                data = {'error': 'claude_busy'} if status == 409 else {'state': 'succeeded', 'account': value['account'], 'result': {'type': 'result', 'result': 'OK'}}
                raw = json.dumps(data).encode()
                self.send_response(status)
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'
    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
    def test_account_message_optional_model_and_receipt(self):
        call = ClaudeCall(self.url, 'fictional-key', 'a', '你好', model='fixture-model')
        receipt = call.result(5)
        self.assertEqual(receipt['result']['result'], 'OK')
        self.assertEqual(self.observed, [('/v1/claude-code/messages', 'Bearer fictional-key', {'account': 'a', 'prompt': '你好', 'model': 'fixture-model'})])
        self.assertFalse(call.cancel())
    def test_error_preserves_status_and_body_without_retry(self):
        call = ClaudeCall(self.url, 'fictional-key', 'b', 'busy')
        with self.assertRaises(APIError) as error:
            call.result(5)
        self.assertEqual(error.exception.status, 409)
        self.assertEqual(error.exception.response, {'error': 'claude_busy'})
        self.assertEqual(len(self.observed), 1)
    def test_cancel_closes_connection(self):
        call = ClaudeCall(self.url, 'fictional-key', 'a', 'wait')
        self.assertTrue(self.arrived.wait(3))
        self.assertTrue(call.cancel())
        with self.assertRaises(CancelledError):
            call.result(5)
        self.assertTrue(self.disconnected.wait(3))

if __name__ == '__main__':
    unittest.main(verbosity=2)
