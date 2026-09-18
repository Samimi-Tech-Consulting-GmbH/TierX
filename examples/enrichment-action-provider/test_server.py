from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("server.py")
SPEC = importlib.util.spec_from_file_location("example_action_server", MODULE_PATH)
server = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(server)


class ProviderContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        server.SECRET = "unit-test-secret"
        server.ACTION_CODE = "example-observer"
        server.DATA_FILE = Path(cls.temp.name) / "deliveries.json"
        cls.httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.httpd.server_port}/"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.thread.join()
        cls.httpd.server_close()
        cls.temp.cleanup()

    def request(self, *, delivery_id="delivery-1", timestamp=None, secret="unit-test-secret"):
        timestamp = str(timestamp or int(time.time()))
        body = json.dumps(
            {
                "spec_version": "1.0",
                "delivery_id": delivery_id,
                "action": {"code": "example-observer"},
                "alert": {"normalized_payload": {"host": {"name": "host-1"}}},
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        digest = hmac.new(
            secret.encode(),
            timestamp.encode() + b"." + delivery_id.encode() + b"." + body,
            hashlib.sha256,
        ).hexdigest()
        request = urllib.request.Request(
            self.url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-TierX-Action-Version": "1",
                "X-TierX-Delivery-ID": delivery_id,
                "X-TierX-Timestamp": timestamp,
                "X-TierX-Signature": f"v1={digest}",
            },
        )
        with urllib.request.urlopen(request) as response:
            return response.status, json.load(response)

    def test_signed_request_and_idempotent_replay(self):
        first = self.request(delivery_id="stable-delivery")
        second = self.request(delivery_id="stable-delivery")
        self.assertEqual(first, second)
        self.assertEqual(first[1]["outcome"], "OBSERVED")
        self.assertIn("host.name", first[1]["context_text"])

    def test_invalid_signature_is_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request(delivery_id="bad-signature", secret="wrong")
        self.assertEqual(error.exception.code, 401)
        error.exception.close()

    def test_stale_timestamp_is_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request(delivery_id="stale", timestamp=int(time.time()) - 301)
        self.assertEqual(error.exception.code, 401)
        error.exception.close()


if __name__ == "__main__":
    unittest.main()
