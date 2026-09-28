"""Skills listing through the CLI, with HTTP replies supplied in memory.

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
EXTENSION = 'io.modelcontextprotocol/skills'
ENTRIES = [
    {'uri': 'skill://review/SKILL.md',
     'frontmatter': {'name': 'review', 'description': 'Review changes',
                     'custom': {'retained': True}},
     'resources': [{'uri': 'skill://review/SKILL.md', 'digest': 'sha256:' + 'a' * 64,
                    'size': 42}],
     'vendorField': 'preserved'},
    {'uri': 'skill://dynamic/SKILL.md',
     'frontmatter': {'name': 'dynamic', 'description': 'Generated workflow'},
     'resources': 'dynamic'},
]


class SkillsTests(unittest.TestCase):
    def run_cli(self, flags=(), advertised=True, legacy=False, failure=False,
                empty=False, experimental=False):
        calls = []
        caps = {'resources': {}}
        if advertised:
            caps['experimental' if experimental else 'extensions'] = {EXTENSION: {}}

        def post(url, payload, headers, timeout, journal, sensitive):
            method = payload['method']
            calls.append(payload)
            result = {}
            error = None
            if method == 'server/discover' and legacy:
                error = {'code': -32601, 'message': 'Method not found'}
            elif method in ('server/discover', 'initialize'):
                result = {'capabilities': caps, 'protocolVersion': '2025-11-25',
                          'supportedVersions': ['2026-07-28'],
                          'serverInfo': {'name': 'skills-test', 'version': '1'}}
            elif method == 'notifications/initialized':
                return APP['Response'](202, {}, b'')
            elif method == 'skills/list':
                if failure:
                    error = {'code': -32601, 'message': 'Skills unavailable'}
                else:
                    cursor = payload['params'].get('cursor')
                    result = {'skills': [] if empty else [ENTRIES[1 if cursor else 0]],
                              'resultType': 'complete', 'ttlMs': 1000,
                              'cacheScope': 'public'}
                    if not cursor and not empty:
                        result['nextCursor'] = 'second-page'
            elif method == 'resources/list':
                result = {'resources': [{'uri': ENTRIES[0]['uri'], 'name': 'review'}]}
            elif method == 'resources/templates/list':
                result = {'resourceTemplates': []}
            else:
                self.fail('Unexpected method: ' + method)
            message = {'jsonrpc': '2.0', 'id': payload.get('id')}
            message['error' if error else 'result'] = error or result
            return APP['Response'](200, {'Content-Type': 'application/json'},
                                   json.dumps(message).encode())

        output = io.StringIO()
        with patch.dict(APP['main'].__globals__, http_post=post), \
                contextlib.redirect_stdout(output):
            status = APP['main']([*flags, 'https://example.com/mcp'])
        self.assertEqual(status, 0)
        return output.getvalue(), calls

    def test_default_pagination_and_full_metadata(self):
        output, calls = self.run_cli(['--json'])
        result = json.loads(output)
        self.assertEqual(result['skills/list']['result']['skills'], ENTRIES)
        self.assertNotIn('nextCursor', result['skills/list']['result'])
        self.assertIn('resources/list', result)  # Overlap is retained.
        pages = [c for c in calls if c['method'] == 'skills/list']
        self.assertEqual(len(pages), 2)
        self.assertEqual(pages[1]['params']['cursor'], 'second-page')
        self.assertIn('_meta', pages[0]['params'])

    def test_explicit_selection_and_duplicate_selection(self):
        output, calls = self.run_cli(['--json', '--list', 'skills', '--list', 'skills'])
        self.assertEqual(set(json.loads(output)), {'server/discover', 'skills/list'})
        self.assertEqual(sum(c['method'] == 'skills/list' for c in calls), 2)

    def test_unadvertised_and_experimental_do_not_autodetect(self):
        for kwargs in ({'advertised': False}, {'experimental': True}):
            with self.subTest(kwargs=kwargs):
                output, calls = self.run_cli(['--json'], **kwargs)
                self.assertNotIn('skills/list', json.loads(output))

    def test_explicit_unadvertised_probe(self):
        output, _ = self.run_cli(['--json', '--list', 'skills'], advertised=False)
        self.assertEqual(json.loads(output)['skills/list']['result']['skills'], ENTRIES)

    def test_info_only_and_resources_selection(self):
        for flags in (['--info-only'], ['--list', 'resources']):
            with self.subTest(flags=flags):
                output, calls = self.run_cli(['--json', *flags])
                self.assertNotIn('skills/list', json.loads(output))

    def test_legacy_advertisement(self):
        output, calls = self.run_cli(['--json'], legacy=True)
        self.assertEqual(json.loads(output)['skills/list']['result']['skills'], ENTRIES)
        self.assertIn('notifications/initialized', [c['method'] for c in calls])
        self.assertNotIn('_meta', next(c['params'] for c in calls if c['method'] == 'skills/list'))

    def test_unprobed_summary_distinguishes_advertised_support(self):
        for legacy in (False, True):
            for flags in (['--info-only'], ['--list', 'resources']):
                with self.subTest(legacy=legacy, flags=flags):
                    output, _ = self.run_cli(flags, legacy=legacy)
                    summary = output.split('SUMMARY')[-1]
                    self.assertIn('tools          not advertised', summary)
                    self.assertIn('prompts        not advertised', summary)
                    self.assertIn('     skills       advertised, not probed', summary)
                    if '--info-only' in flags:
                        self.assertIn('resources      advertised, not probed', summary)
                    else:
                        self.assertIn('resources      1 (review)', summary)

    def test_report_preserves_fields_and_summarizes_frontmatter_names(self):
        output, _ = self.run_cli(['--list', 'skills'])
        self.assertIn('"custom": {"retained": true}', output)
        self.assertIn('"vendorField": "preserved"', output)
        self.assertIn('"resources": "dynamic"', output)
        summary = output.split('SUMMARY')[-1]
        self.assertIn('2 (review, dynamic)', summary)
        self.assertIn('     skills       2 (review, dynamic)', summary)
        self.assertLess(summary.index('extensions'), summary.index('     skills'))

    def test_summary_omits_unadvertised_skills_even_when_explicit(self):
        for flags in ([], ['--list', 'skills']):
            output, _ = self.run_cli(flags, advertised=False)
            summary = output.split('SUMMARY')[-1]
            self.assertNotRegex(summary, r'(?m)^\s+skills\s')

    def test_summary_groups_skills_under_its_extension(self):
        from types import SimpleNamespace
        transport = SimpleNamespace(era='modern', version='2026-07-28', session_id=None)
        info = {'capabilities': {'extensions': {
            'com.example/before': {}, EXTENSION: {}, 'com.example/after': {},
        }}}
        rows = APP['summarise']('url', transport, info, ['skills'],
                                {'skills': (2, ['review', 'dynamic'])})
        self.assertEqual(rows[-4:], [
            ('extensions', 'com.example/before'), ('', EXTENSION),
            ('  skills', '2 (review, dynamic)'), ('', 'com.example/after'),
        ])

    def test_empty_and_failed_list(self):
        output, _ = self.run_cli(['--list', 'skills'], empty=True)
        self.assertIn('     skills       0', output)
        output, _ = self.run_cli(['--list', 'skills'], failure=True)
        self.assertIn('     skills       error -32601 Skills unavailable', output)
        output, _ = self.run_cli(['--json', '--list', 'skills'], failure=True)
        self.assertEqual(json.loads(output)['skills/list']['error']['code'], -32601)


if __name__ == '__main__':
    unittest.main()
