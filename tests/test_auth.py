"""Authorization challenges through the CLI, with HTTP replies supplied in memory.

Run: python3 -m unittest discover -s tests
"""
import contextlib
import io
import json
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch


APP = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'mcp-inspect'))
CHALLENGE = 'Bearer resource_metadata="https://example.com/.well-known/oauth-protected-resource"'


class AuthTests(unittest.TestCase):
    def run_cli(self, flags=(), status=401, challenge=True, body=True, env=None):
        calls = []

        def post(url, payload, headers, timeout, journal, sensitive):
            calls.append(payload['method'])
            reply = {'Content-Type': 'application/json'}
            if challenge:
                reply['WWW-Authenticate'] = CHALLENGE if challenge is True else challenge
            message = {'jsonrpc': '2.0', 'id': None,
                       'error': {'code': -32000, 'message': 'Unauthorized'}}
            return APP['Response'](status, reply,
                                   json.dumps(message).encode() if body else b'')

        output, errors = io.StringIO(), io.StringIO()
        with patch.dict(APP['main'].__globals__, http_post=post), \
                patch.dict('os.environ', env or {}, clear=False), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = APP['main']([*flags, 'https://example.com/mcp'])
        return code, output.getvalue(), errors.getvalue(), calls

    def test_jsonrpc_error_under_401_is_auth_not_no_mcp(self):
        for era, method in (('auto', 'server/discover'), ('modern', 'server/discover'),
                            ('legacy', 'initialize')):
            with self.subTest(era=era):
                code, output, _, calls = self.run_cli(['--era', era])
                self.assertEqual(code, 1)
                self.assertEqual(calls, [method])  # no legacy fallback
                summary = output.split('SUMMARY')[-1]
                self.assertIn(APP['AUTH_REQUIRED_OAUTH'], summary)
                self.assertNotIn(APP['NO_MCP'], output)
                self.assertIn('WWW-Authenticate', output)
                self.assertIn('MCP_AUTH_TOKEN', output)
                self.assertIn(APP['PLACEHOLDER_HINT'], ' '.join(output.split()))

    def test_401_without_body(self):
        code, output, _, _ = self.run_cli(body=False, challenge=False)
        self.assertEqual(code, 1)
        summary = output.split('SUMMARY')[-1]
        self.assertIn(APP['AUTH_REQUIRED'], summary)
        self.assertNotIn('OAuth', summary)

    def test_bare_bearer_challenge_is_not_called_oauth(self):
        _, output, _, _ = self.run_cli(challenge='Bearer realm="api"')
        summary = output.split('SUMMARY')[-1]
        self.assertIn(APP['AUTH_REQUIRED'], summary)
        self.assertNotIn('OAuth', summary)

    def test_rejected_credentials_say_so(self):
        code, output, _, _ = self.run_cli(env={'MCP_AUTH_TOKEN': 'bad'})
        self.assertIn('credentials sent were not accepted', ' '.join(output.split()))
        self.assertNotIn('Set the MCP_AUTH_TOKEN', output)
        self.assertNotIn('placeholder', output)

    def test_403_with_challenge_is_auth_but_bare_403_is_not(self):
        _, output, _, _ = self.run_cli(status=403)
        self.assertIn(APP['AUTH_REQUIRED'], output)
        _, output, _, _ = self.run_cli(status=403, challenge=False)
        self.assertNotIn(APP['AUTH_REQUIRED'], output)

    def test_json_mode_reports_on_stderr(self):
        code, output, errors, _ = self.run_cli(['--json'])
        self.assertEqual(code, 1)
        self.assertIn('server/discover', json.loads(output))
        self.assertIn('requires credentials', errors)


if __name__ == '__main__':
    unittest.main()
