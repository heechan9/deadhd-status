"""Independent review regressions: bounded acceptance, visible supporting work and safe rendering.

All GitHub responses are fixtures. Node checks syntax/summary logic, not browser layout.
"""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import build
import completion
import gen_mapping
from test_completion import by_id, load_spec, tally, PROJECT, SLUG
from test_live_status import AT, build_with, ci, load_base, pr_record


class ReviewedMapping(unittest.TestCase):
    def test_u01_done_does_not_complete_submission_demo(self):
        data, _ = build_with(PROJECT, OSError('offline'))
        item = by_id(data)['n-web']
        self.assertEqual((item['state'], item['completion']['status']), ('left', 'partial'))
        self.assertEqual((item['completion']['done'], item['completion']['total']), (1, 3))
        done = item['substeps'][0]
        self.assertEqual(done['state'], 'done')
        self.assertIn('6386608455', done['href'])
        self.assertIn('20dd1c4', done['label'])
        self.assertIn('1280/360/390px', done['label'])
        self.assertTrue(any('JSON' in x and '다운로드' in x for x in item['completion']['remaining']))
        self.assertEqual(tally(data), (6, 13))

    def test_team_acceptance_is_formal_receipt_only(self):
        spec = load_spec()['cards']['submission-team-intake']
        self.assertEqual({s['id'] for s in spec['subtasks']}, {'minjae-submitted', 'formal-roster-receipts'})
        self.assertTrue(all(s['kind'] == 'material-intake' for s in spec['subtasks']))
        self.assertFalse(spec.get('autoComplete'))
        data, _ = build_with(PROJECT, gen_mapping.codex_report)
        item = by_id(data)['submission-team-intake']
        self.assertEqual((item['completion']['done'], item['completion']['total']), (1, 2))
        self.assertEqual((item['completion']['milestonesDone'], item['completion']['milestonesTotal']), (2, 7))
        self.assertIn('전체 명단', item['completion']['remaining'][0])
        self.assertFalse(any('계약' in x or '외부' in x or '본인 검토' in x for x in item['completion']['remaining']))

    def test_draft_preparation_and_separate_ci_are_visible_not_merges(self):
        data, _ = build_with(PROJECT, gen_mapping.codex_report)
        item = by_id(data)['draft-work']
        self.assertEqual(item['state'], 'side')
        self.assertEqual((item['completion']['done'], item['completion']['total']), (1, 5))
        self.assertEqual((item['completion']['milestonesDone'], item['completion']['milestonesTotal']), (6, 6))
        for head in ('6436a0a', '90ef2a6', '36115d0'):
            self.assertEqual(sum(head in s['label'] and s['state'] == 'done' for s in item['substeps']), 2)
        self.assertTrue(all(s['rule']['type'] == 'manual' for s in load_spec()['cards']['draft-work']['milestones']))

    def test_supporting_progress_cannot_block_or_complete_parent(self):
        spec = load_spec(); items = copy.deepcopy(load_base(SLUG)['items'])
        before = completion.evaluate(spec, items, {})['submission-team-intake']
        for sub in spec['cards']['submission-team-intake']['milestones']:
            sub['rule']['status'] = 'done'
        after = completion.evaluate(spec, items, {})['submission-team-intake']
        for key in ('state', 'status', 'done', 'total'):
            self.assertEqual(before[key], after[key])
        self.assertEqual(after['state'], 'left')

    def test_supporting_progress_cannot_contain_automatic_rules(self):
        spec = load_spec()
        spec['cards']['draft-work']['milestones'][0].update(kind='code-merge', rule={'type': 'pr_merged', 'pr': 'o/r#1'})
        with self.assertRaisesRegex(completion.SpecError, 'milestones'):
            completion.validate_spec(spec, load_base(SLUG)['items'])

    def test_ulsan_acceptance_is_final_document_handling_not_correction(self):
        spec = load_spec()['cards']['c-ulsan']
        self.assertEqual(spec['subtasks'][-1]['id'], 'ulsan-final-document-handling')
        self.assertEqual(spec['subtasks'][-1]['rule']['status'], 'left')
        self.assertNotIn('불일치 해소', spec['subtasks'][-1]['label'])
        data, _ = build_with(PROJECT, gen_mapping.codex_report)
        item = by_id(data)['c-ulsan']
        self.assertEqual(item['state'], 'blocked')
        self.assertEqual((item['completion']['done'], item['completion']['total']), (2, 3))


class ReviewedLogicAndRendering(unittest.TestCase):
    def test_skipped_or_neutral_workflow_is_not_ci_success(self):
        for conclusions in (['skipped'], ['neutral'], ['success', 'skipped'], ['success', 'neutral']):
            runs = [ci(name=f'CI {i}', conclusion=c) for i, c in enumerate(conclusions)]
            record = pr_record(1, 'o/r', ci=runs)
            self.assertEqual(completion.judge_pr({'type': 'pr_ci_success'}, record)[0], 'left')
            self.assertNotEqual(build.ci_state(runs)[0], 'done')
        self.assertEqual(completion.judge_pr({'type': 'pr_ci_success'}, pr_record(1, 'o/r', ci=[ci()]))[0], 'done')

    def render_html(self):
        data, _ = build_with(PROJECT, gen_mapping.codex_report)
        with tempfile.TemporaryDirectory() as tmp:
            out = str(Path(tmp, 'p.html'))
            build.render(data, out)
            return Path(out).read_text()

    def test_compact_segments_have_partial_class_and_required_scope(self):
        html = self.render_html()
        self.assertIn('requiredItems.map(i => `<span class="${i.state}${i.completion', html)
        self.assertNotIn('items.map(i => `<span class="${i.state}"', html)

    def test_render_has_no_token_or_private_receipt_link(self):
        with patch.dict(os.environ, {'GITHUB_TOKEN': 'test-token-never-publish-123'}):
            html = self.render_html()
        for denied in ('test-token-never-publish-123', 'drive.google.com', 'Authorization:', '/workspace/'):
            self.assertNotIn(denied, html)

    def test_rendered_javascript_parses(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node unavailable; no installation attempted')
        from html.parser import HTMLParser
        class Scripts(HTMLParser):
            def __init__(self):
                super().__init__(); self.inside = False; self.parts = []
            def handle_starttag(self, tag, attrs):
                if tag == 'script': self.inside = dict(attrs).get('type') != 'application/json'
            def handle_endtag(self, tag):
                if tag == 'script': self.inside = False
            def handle_data(self, data):
                if self.inside: self.parts.append(data)
        parser = Scripts(); parser.feed(self.render_html())
        self.assertTrue(parser.parts)
        for script in parser.parts:
            result = subprocess.run([node, '--check'], input=script, text=True, capture_output=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_summary_js_displays_supporting_work_and_escapes_text(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node unavailable; no installation attempted')
        data, _ = build_with(PROJECT, gen_mapping.codex_report)
        by_id(data)['draft-work']['label'] = '<img src=x onerror=alert(1)>'
        script = "const items=" + json.dumps(data['items']) + ";const requiredDone=6,requiredTotal=13;const box={};const document={getElementById:()=>box};" + build.COMPLETION_JS + ";console.log(JSON.stringify(box));"
        result = subprocess.run([node, '-e', script], text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        box = json.loads(result.stdout)
        self.assertFalse(box['hidden'])
        self.assertIn('참고 진행 6/6 (부모 완료 조건 아님)', box['innerHTML'])
        self.assertIn('&lt;img', box['innerHTML'])
        self.assertNotIn('<img', box['innerHTML'])


if __name__ == '__main__':
    unittest.main()
