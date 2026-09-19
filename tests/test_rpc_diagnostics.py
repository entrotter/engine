"""An upstream error envelope is untrusted, including fields conventionally numeric."""
import io
import json
import unittest
from unittest.mock import patch

from entrotter_engine.rpc import RPC, RPCRejected


class RPCDiagnosticTests(unittest.TestCase):
    def rejection(self, error):
        rpc = RPC('https://example.invalid')
        reply = io.BytesIO(json.dumps({'jsonrpc': '2.0', 'id': 1, 'error': error}).encode())
        with patch.object(rpc.opener, 'open', return_value=reply):
            with self.assertRaises(RPCRejected) as caught:
                rpc.call('eth_call', [])
        return str(caught.exception)

    def test_untrusted_code_cannot_enter_diagnostics(self):
        marker = 'UPSTREAM_PRIVATE_DIAGNOSTIC_MARKER'
        for code in [marker, {'nested': marker}, [marker]]:
            with self.subTest(code=code):
                message = self.rejection({'code': code, 'message': 'ignored upstream message'})
                self.assertNotIn(marker, message)
                self.assertEqual(message, 'RPC rejected eth_call')

    def test_error_message_and_data_are_never_echoed(self):
        message = self.rejection({'code': -32000, 'message': 'PRIVATE_MESSAGE', 'data': 'PRIVATE_DATA'})
        self.assertEqual(message, 'RPC rejected eth_call')

    def test_non_object_error_does_not_echo_untrusted_text(self):
        self.assertEqual(self.rejection('PRIVATE_ENVELOPE'), 'RPC rejected eth_call')


if __name__ == '__main__':
    unittest.main()
