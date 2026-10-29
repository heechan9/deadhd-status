"""완료 판정 규칙(completion.py)과 상단 노드·집계·카드 상세의 일치를 확인한다. 네트워크를 쓰지 않는다(모두 mock/offline).

실제 GitHub API 에 대한 성공 검증이 아니다: 이 환경의 실제 조회는 HTTP 403 이었고, 여기서는 응답 형태를 흉내 낸 값으로 규칙만 확인한다."""
import copy
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import urllib.error
from datetime import timedelta
from pathlib import Path

import build
import completion
import gen_mapping
from test_live_status import AT, SHA_A, build_with, ci, load_base, pr_record

REPO = 'heechan9/bunkering-ai'
SLUG = 'bunkering-ai'
PROJECT = build.PROJECTS[0]
OTHER = build.PROJECTS[1]


def load_spec():
    return completion.load_spec(build.ROOT, SLUG)


def merged(n, sha='d' * 7, ci_list=None, head=SHA_A):
    r = pr_record(n, REPO, 'closed', False, True, ci_list if ci_list is not None else [ci()], head=head)
    r['mergeSha'] = sha
    return r


def by_id(data):
    return {i['id']: i for i in data['items']}


def required(items):
    return [i for i in items if i.get('countScope') == 'submission']


def tally(data):
    req = required(data['items'])
    return sum(i['state'] == 'done' for i in req), len(req)


def all_draft_work_merged(repo, n):
    if (repo, n) == (REPO, 126):
        return merged(126, '984411c')
    return merged(n)


class TinySpec(unittest.TestCase):
    """합성 카드로 규칙 자체를 확인한다."""

    def items(self):
        return [{'id': 'code', 'state': 'left', 'countScope': 'after-submission', 'label': 'C', 'sub': 's', 'body': ''},
                {'id': 'research', 'state': 'left', 'countScope': 'submission', 'label': 'R', 'sub': 's', 'body': ''}]

    def spec(self):
        return {'cards': {
            'code': {'target': 'code-merge', 'criterion': '두 PR 병합', 'evidenceLevel': 'public', 'checkedAt': '2026-10-27 15:00 KST',
                     'autoComplete': True, 'subtasks': [
                         {'id': 'a', 'label': 'a 병합', 'kind': 'code-merge', 'rule': {'type': 'pr_merged', 'pr': 'o/r#1'}},
                         {'id': 'b', 'label': 'b 병합', 'kind': 'code-merge', 'rule': {'type': 'pr_merged', 'pr': 'o/r#2'}}]},
            'research': {'target': 'research-result', 'criterion': '연구 성과 입증', 'evidenceLevel': 'public', 'checkedAt': '2026-10-27 15:00 KST',
                         'subtasks': [
                             {'id': 'ci', 'label': 'CI 성공', 'kind': 'ci-pass', 'rule': {'type': 'pr_ci_success', 'pr': 'o/r#3'}},
                             {'id': 'merge', 'label': '병합', 'kind': 'code-merge', 'rule': {'type': 'pr_merged', 'pr': 'o/r#3'}},
                             {'id': 'result', 'label': '연구 성과 확인', 'kind': 'research-result', 'rule': {'type': 'manual', 'status': 'left'}}]}}}

    def prs(self, **kw):
        out = {}
        for n, rec in kw.items():
            out['o/r#' + n[1:]] = {'ok': True, 'fetchedAt': AT.isoformat(), 'data': rec}
        return out

    def run_apply(self, prs, items=None, spec=None):
        items = items or self.items()
        res = completion.apply(spec or self.spec(), items, prs, AT, build.parse_kst, 3)
        return {i['id']: i for i in items}, res

    def test_merged_prs_complete_only_the_explicit_code_card(self):
        prs = self.prs(p1=pr_record(1, 'o/r', 'closed', False, True), p2=pr_record(2, 'o/r', 'closed', False, True),
                       p3=pr_record(3, 'o/r', 'closed', False, True, [ci()]))
        got, _ = self.run_apply(prs)
        self.assertEqual(got['code']['state'], 'done')
        self.assertEqual(got['code']['completion']['status'], 'complete')
        self.assertTrue(all(s['state'] == 'done' for s in got['code']['substeps']))
        self.assertEqual(got['research']['state'], 'left')            # 병합·CI 성공이어도 연구 성과 카드는 그대로
        self.assertEqual(got['research']['completion']['status'], 'partial')
        self.assertEqual(got['research']['completion']['done'], 2)

    def test_one_of_two_merged_is_partial_not_done(self):
        prs = self.prs(p1=pr_record(1, 'o/r', 'closed', False, True), p2=pr_record(2, 'o/r'))
        got, _ = self.run_apply(prs)
        self.assertEqual(got['code']['state'], 'left')
        self.assertEqual(got['code']['completion']['status'], 'partial')
        self.assertIn('하위 1/2 완료', got['code']['sub'])
        self.assertEqual([s['state'] for s in got['code']['substeps']], ['done', 'left'])

    def test_draft_open_and_closed_unmerged_are_not_done(self):
        for rec in (pr_record(1, 'o/r', draft=True), pr_record(1, 'o/r', draft=False),
                    pr_record(1, 'o/r', 'closed', False, False)):
            got, _ = self.run_apply(self.prs(p1=rec, p2=pr_record(2, 'o/r', 'closed', False, True)))
            self.assertEqual(got['code']['state'], 'left')
            self.assertEqual(got['code']['completion']['done'], 1)

    def test_ci_success_alone_never_promotes_other_kinds(self):
        prs = self.prs(p3=pr_record(3, 'o/r', 'open', False, False, [ci()]))
        got, _ = self.run_apply(prs)
        self.assertEqual(got['research']['state'], 'left')
        self.assertEqual(got['research']['completion']['status'], 'partial')
        self.assertEqual([s['state'] for s in got['research']['substeps']], ['done', 'left', 'left'])

    def test_wrong_base_or_merge_sha_or_head_is_not_done(self):
        spec = self.spec()
        spec['cards']['code']['subtasks'][0]['rule'].update(mergeSha='abc1234')
        rec = pr_record(1, 'o/r', 'closed', False, True)
        rec['mergeSha'] = 'fffffff'
        got, _ = self.run_apply(self.prs(p1=rec, p2=pr_record(2, 'o/r', 'closed', False, True)), spec=spec)
        self.assertEqual(got['code']['state'], 'left')
        self.assertIn('재검토', got['code']['body'])
        other_base = pr_record(2, 'o/r', 'closed', False, True)
        other_base['baseRef'] = 'dev'
        got, _ = self.run_apply(self.prs(p1=pr_record(1, 'o/r', 'closed', False, True), p2=other_base))
        self.assertEqual(got['code']['state'], 'left')
        spec = self.spec()
        spec['cards']['research']['subtasks'][0]['rule']['head'] = 'bbbbbbb'
        got, _ = self.run_apply(self.prs(p3=pr_record(3, 'o/r', 'open', False, False, [ci()], head=SHA_A)), spec=spec)
        self.assertEqual(got['research']['substeps'][0]['state'], 'left')

    def test_failed_or_missing_fetch_creates_no_new_completion(self):
        for prs in ({}, {'o/r#1': {'ok': False, 'error': 'HTTPError 403'}, 'o/r#2': {'ok': False, 'error': 'HTTPError 403'}},
                    # 오래된 캐시: 직전 성공 기록(병합)이 있어도 ok=False 면 새 완료를 만들지 않는다
                    {'o/r#1': dict(ok=False, error='URLError', fetchedAt=(AT - timedelta(hours=9)).isoformat(), data=pr_record(1, 'o/r', 'closed', False, True)),
                     'o/r#2': dict(ok=False, error='URLError', fetchedAt=(AT - timedelta(hours=9)).isoformat(), data=pr_record(2, 'o/r', 'closed', False, True))}):
            got, _ = self.run_apply(prs)
            self.assertEqual(got['code']['state'], 'left')
            self.assertEqual(got['code']['completion']['done'], 0)
            self.assertEqual(got['code']['completion']['unverified'], 2)
            self.assertIn('자동 확인 불가', got['code']['body'])

    def test_curated_done_is_kept_when_live_is_unavailable_and_conflict_is_shown_when_live_disagrees(self):
        spec = self.spec()
        for s in spec['cards']['code']['subtasks']:
            s['curated'] = {'status': 'done'}
        got, _ = self.run_apply({}, spec=spec)
        self.assertEqual(got['code']['state'], 'done')                      # 수동 정리의 기존 완료 유지(새 완료 아님)
        self.assertEqual([s['state'] for s in got['code']['substeps']], ['done', 'done'])
        self.assertIn('수동 정리 기준 완료, 자동 확인 불가', got['code']['body'])
        # 조회가 성공했는데 미병합이면: 자동으로 되돌리지 않고 불일치를 표시한다
        items = self.items()
        items[0]['state'] = 'done'
        got, _ = self.run_apply(self.prs(p1=pr_record(1, 'o/r'), p2=pr_record(2, 'o/r', 'closed', False, True)), items=items, spec=spec)
        self.assertEqual(got['code']['state'], 'done')
        self.assertTrue(got['code']['completion']['conflict'])
        self.assertIn('불일치', got['code']['body'])
        self.assertEqual(got['code']['substeps'][0]['state'], 'left')

    def test_countscope_and_labels_untouched(self):
        items = self.items()
        before = copy.deepcopy(items)
        self.run_apply(self.prs(p1=merged(1), p2=merged(2), p3=merged(3)), items=items)
        for a, b in zip(items, before):
            for key in ('countScope', 'label', 'id'):
                self.assertEqual(a[key], b[key])

    def test_idempotent(self):
        prs = self.prs(p1=merged(1), p2=pr_record(2, 'o/r'), p3=merged(3))
        first, _ = self.run_apply(prs)
        second, _ = self.run_apply(prs)
        self.assertEqual(first, second)


class SpecValidation(unittest.TestCase):
    def setUp(self):
        self.base = load_base(SLUG)
        self.spec = load_spec()

    def problems(self, spec):
        with self.assertRaises(completion.SpecError) as cm:
            completion.validate_spec(spec, self.base['items'])
        return str(cm.exception)

    def test_real_spec_is_valid_and_covers_every_card(self):
        completion.validate_spec(self.spec, self.base['items'])
        self.assertEqual(set(self.spec['cards']), {i['id'] for i in self.base['items']})
        self.assertEqual(len(self.spec['cards']), 32)

    def test_missing_extra_and_forbidden_keys(self):
        spec = copy.deepcopy(self.spec)
        del spec['cards']['accept']
        spec['cards']['ghost'] = spec['cards']['overview']
        spec['cards']['overview']['state'] = 'done'
        spec['cards']['seeds']['countScope'] = 'submission'
        text = self.problems(spec)
        for needle in ('accept: 완료 정의가 없다', 'ghost: 카드가 없는데', 'overview: state', 'seeds: countScope'):
            self.assertIn(needle, text)

    def test_auto_rules_only_for_auto_kinds(self):
        spec = copy.deepcopy(self.spec)
        card = spec['cards']['submission-team-intake']
        card['subtasks'][0]['rule'] = {'type': 'pr_merged', 'pr': f'{REPO}#149'}      # material-intake 에 병합 규칙
        card['subtasks'][1]['kind'] = 'code-merge'                                    # 자동 종류에 manual 규칙
        text = self.problems(spec)
        self.assertIn('pr_merged 규칙은 kind=code-merge', text)
        self.assertIn('자동 종류(code-merge)는 manual 규칙으로', text)

    def test_cannot_auto_complete_research_approval_contract_or_final_cards(self):
        for cid in ('fair', 'submission-final-paper', 'submission-research-remaining', 'submission-team-intake', 'c-ulsan'):
            spec = copy.deepcopy(self.spec)
            spec['cards'][cid]['autoComplete'] = True
            self.assertIn('autoComplete', self.problems(spec), cid)

    def test_manual_done_needs_evidence_or_explicit_level_and_time(self):
        spec = copy.deepcopy(self.spec)
        sub = spec['cards']['fair']['subtasks'][2]
        sub.pop('evidence'); sub.pop('checkedAt')
        self.assertIn('수동 완료는 공개 URL 증거', self.problems(spec))

    def test_bad_pr_reference_and_unknown_rule(self):
        spec = copy.deepcopy(self.spec)
        spec['cards']['arctic']['subtasks'][0]['rule']['pr'] = 'not-a-pr'
        spec['cards']['arctic']['subtasks'][1]['rule'] = {'type': 'vibes'}
        text = self.problems(spec)
        self.assertIn('PR 참조 형식 오류', text)
        self.assertIn('알 수 없는 규칙', text)

    def test_bad_spec_stops_the_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, 'content'))
            shutil.copy(os.path.join(build.ROOT, 'content', SLUG + '.base.json'), tmp + '/content/')
            bad = copy.deepcopy(self.spec)
            bad['cards']['accept']['target'] = 'nonsense'
            Path(tmp, 'content', SLUG + '.completion.json').write_text(json.dumps(bad), encoding='utf-8')
            orig = build.ROOT
            build.ROOT = tmp
            try:
                with self.assertRaises(completion.SpecError):
                    build_with(PROJECT, lambda r, n: pr_record(n, r))
            finally:
                build.ROOT = orig


class BunkeringCards(unittest.TestCase):
    """실제 content 32카드 기준."""

    def setUp(self):
        self.base = load_base(SLUG)
        self.spec = load_spec()

    def test_only_code_merge_cards_may_auto_complete(self):
        auto = {cid for cid, c in self.spec['cards'].items() if c.get('autoComplete')}
        self.assertEqual(auto, {'draft-work', 'time-intake', 'arctic', 'english', 'voyage-demand'})
        for cid in auto:
            self.assertEqual(self.spec['cards'][cid]['target'], 'code-merge')
            self.assertNotEqual(self.base_state(cid), None)
        required_ids = {i['id'] for i in required(self.base['items'])}
        self.assertFalse(auto & required_ids)              # 필수 항목은 어느 것도 PR 병합만으로 완료되지 않는다

    def base_state(self, cid):
        return next(i['countScope'] for i in self.base['items'] if i['id'] == cid)

    def test_all_prs_merged_completes_draft_work_but_not_required_count(self):
        def everything_good(repo, n):
            head = '90ef2a6' + '0' * 33 if n == 147 else SHA_A
            r = all_draft_work_merged(repo, n)
            r['headSha'] = head
            return r
        data, state = build_with(PROJECT, everything_good)
        got = by_id(data)
        self.assertEqual(got['draft-work']['state'], 'done')                # 코드 반영 카드는 모두 병합되면 완료
        self.assertEqual(got['draft-work']['completion']['status'], 'complete')
        self.assertEqual(state['completion']['draft-work']['state'], 'done')
        self.assertEqual(tally(data), (7, 13))                              # 필수 집계는 그대로
        for cid in ('submission-final-paper', 'submission-video', 'submission-project-report', 'submission-team-intake',
                    'submission-research-remaining', 'c-ulsan', 'n-web', 'fair', 'realship', 'wait', 'o-ops'):
            self.assertEqual(got[cid]['state'], next(i['state'] for i in self.base['items'] if i['id'] == cid), cid)

    def test_codex_baseline_gives_partial_not_done(self):
        data, state = build_with(PROJECT, gen_mapping.codex_report)
        got = by_id(data)
        dw = got['draft-work']
        self.assertEqual(dw['state'], 'side')
        self.assertEqual((dw['completion']['status'], dw['completion']['done'], dw['completion']['total']), ('partial', 1, 5))
        self.assertEqual([s['state'] for s in dw['substeps'] if s.get('completionRole') != 'supporting'],
                         ['done', 'left', 'left', 'left', 'left'])
        self.assertIn('하위 1/5 완료', dw['sub'])
        self.assertIn('#119', dw['body'])
        self.assertEqual(tally(data), (7, 13))

    def test_required_cards_never_become_done_from_any_pr_or_ci_combination(self):
        base_req = {i['id']: i['state'] for i in required(self.base['items'])}
        variants = [
            lambda r, n: merged(n),
            lambda r, n: pr_record(n, r, 'closed', False, False, [ci(conclusion='failure')]),
            lambda r, n: pr_record(n, r, draft=False, ci=[ci()]),
            OSError('offline'),
        ]
        for factory in variants:
            data, _ = build_with(PROJECT, factory)
            got = by_id(data)
            for cid, st in base_req.items():
                self.assertEqual(got[cid]['state'], st, cid)
            self.assertEqual(tally(data), (7, 13))

    def test_compound_cards_show_sub_items_and_pending_reasons(self):
        data, _ = build_with(PROJECT, gen_mapping.codex_report)
        got = by_id(data)
        intake = got['submission-team-intake']
        self.assertEqual(intake['state'], 'left')
        self.assertEqual(intake['completion']['status'], 'partial')
        states = {s['label'][:6]: s['state'] for s in intake['substeps']}
        self.assertIn('done', states.values())
        self.assertTrue(any('C01–C06' in s['label'] and s['state'] == 'left' for s in intake['substeps']))
        self.assertTrue(any('기예 Python' in s['label'] and s['state'] == 'now' for s in intake['substeps']))
        self.assertTrue(any('기예 pnpm' in s['label'] and s['state'] == 'left' for s in intake['substeps']))
        report = got['submission-project-report']
        self.assertTrue(any('18쪽' in s['label'] and s['state'] == 'done' for s in report['substeps']))   # v9 작성 완료와 HWP 최종 승인은 별개
        self.assertTrue(any('Forms' in s['label'] and s['state'] == 'left' for s in report['substeps']))
        self.assertEqual(report['completion']['done'], 2)
        self.assertEqual(got['c-ulsan']['state'], 'blocked')
        self.assertEqual(got['c-ulsan']['completion']['done'], 2)
        for cid in ('submission-team-intake', 'submission-project-report', 'c-ulsan'):
            self.assertIn('남은 조건', got[cid]['body'])

    def test_countscope_preserved_on_every_card_and_denominator_fixed(self):
        for factory in (lambda r, n: merged(n), gen_mapping.codex_report, OSError('x')):
            data, _ = build_with(PROJECT, factory)
            got = by_id(data)
            for item in self.base['items']:
                self.assertEqual(got[item['id']]['countScope'], item['countScope'], item['id'])
                self.assertEqual(got[item['id']].get('countScopeReason'), item.get('countScopeReason'))
            self.assertEqual(tally(data)[1], 13)

    def test_card_state_node_and_summary_use_one_basis(self):
        data, state = build_with(PROJECT, gen_mapping.codex_report)
        for item in data['items']:
            if 'completion' not in item:
                continue
            self.assertEqual(state['completion'][item['id']]['state'], item['state'])
            self.assertEqual(state['completion'][item['id']]['status'], item['completion']['status'])
            acceptance = [s for s in item.get('substeps', []) if s.get('completionRole') != 'supporting']
            supporting = [s for s in item.get('substeps', []) if s.get('completionRole') == 'supporting']
            n = len(acceptance)
            self.assertEqual(n, item['completion']['total'])
            self.assertEqual(sum(s['state'] == 'done' for s in acceptance), item['completion']['done'])
            self.assertEqual(len(supporting), item['completion']['milestonesTotal'])
            self.assertEqual(sum(s['state'] == 'done' for s in supporting), item['completion']['milestonesDone'])
            if item['completion']['status'] == 'partial':
                self.assertIn(f'하위 {item["completion"]["done"]}/{item["completion"]["total"]} 완료', item['sub'])
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, 'p.html')
            build.render(data, out)
            html = Path(out).read_text(encoding='utf-8')
        for needle in ('completionSummary', "fnode ' + it.state + (it.completion", 'requiredDone', '하위 조건 완료'):
            self.assertIn(needle, html)
        embedded = json.loads(html.split('const data = ', 1)[1].split(';\n', 1)[0]) if 'const data = ' in html else None
        if embedded:
            self.assertEqual(sum(i['state'] == 'done' for i in required(embedded['items'])), tally(data)[0])

    def test_idempotent_across_builds_and_state_roundtrip(self):
        d1, s1 = build_with(PROJECT, gen_mapping.codex_report)
        d2, s2 = build_with(PROJECT, gen_mapping.codex_report)
        self.assertEqual(d1, d2)
        self.assertEqual(s1['completion'], s2['completion'])
        d3, s3 = build_with(PROJECT, gen_mapping.codex_report, prev={SLUG: s1})
        self.assertEqual(d1['items'], d3['items'])          # 직전 state 를 이어받아도 같은 결과
        body = by_id(d3)['draft-work']['body']
        self.assertEqual(body.count('[완료 판정]'), 1)
        self.assertEqual(body.count('[자동 조회'), 1)

    def test_failure_stays_visible_and_stale_cache_creates_nothing(self):
        d_ok, s_ok = build_with(PROJECT, all_draft_work_merged, at=AT - timedelta(hours=6))
        self.assertEqual(by_id(d_ok)['draft-work']['state'], 'done')
        d, s = build_with(PROJECT, urllib.error.HTTPError('u', 403, 'forbidden', {}, None), prev={SLUG: s_ok})
        got = by_id(d)
        self.assertEqual(got['draft-work']['state'], 'side')               # 오래된 캐시로는 완료를 만들지 않는다
        self.assertEqual(got['draft-work']['completion']['unverified'], 5)  # 자동 조회는 5건 모두 불가; 10/29 수동 확인된 네 병합은 유지
        self.assertEqual(got['draft-work']['completion']['done'], 4)
        self.assertIn('조회 실패', got['draft-work']['body'])
        self.assertIn('pr-live-failed', got)
        self.assertEqual(tally(d), (7, 13))
        # 이미 완료로 정리된 코드 반영 카드(time-intake)는 조회 실패로 되돌아가지 않지만 확인 불가가 보인다
        self.assertEqual(got['time-intake']['state'], 'done')
        self.assertEqual(got['time-intake']['completion']['unverified'], 5)
        self.assertIn('자동 확인 불가', got['time-intake']['body'])

    def test_live_contradiction_is_flagged_not_reverted(self):
        data, _ = build_with(PROJECT, lambda r, n: pr_record(n, r, draft=True))
        card = by_id(data)['time-intake']
        self.assertEqual(card['state'], 'done')
        self.assertTrue(card['completion']['conflict'])
        self.assertIn('불일치', card['body'])

    def test_existing_dones_have_explicit_basis(self):
        base_done = [i['id'] for i in required(self.base['items']) if i['state'] == 'done']
        self.assertEqual(sorted(base_done), sorted(['accept', 'overview', 'official', 'seeds', 'public', 'submission-raw-recheck', 'submission-research-remaining']))
        for cid in base_done:
            card = self.spec['cards'][cid]
            self.assertIn(card['evidenceLevel'], ('public', 'curated-only'))
            if card['evidenceLevel'] == 'curated-only':       # 공개 URL 로 확인되지 않은 수동 정리는 그렇게 표시된다
                data, _ = build_with(PROJECT, OSError('x'))
                self.assertIn('공개 URL 없음·미확인', by_id(data)[cid]['body'])


class OtherProjectAndDocs(unittest.TestCase):
    def test_adversarial_project_unchanged_by_completion(self):
        base = load_base(OTHER['slug'])
        for factory in (lambda r, n: merged(n), OSError('x')):
            data, state = build_with(OTHER, factory)
            got = by_id(data)
            self.assertNotIn('completion', state)
            for item in base['items']:
                self.assertNotIn('completion', got[item['id']])
                self.assertNotIn('substeps', got[item['id']]) if 'substeps' not in item else None
                self.assertEqual(got[item['id']]['state'], item['state'])
                self.assertEqual(got[item['id']]['countScope'], item.get('countScope'))
                self.assertNotIn('[완료 판정]', got[item['id']]['body'])

    def test_mapping_doc_is_in_sync_and_covers_all_cards(self):
        text = Path(build.ROOT, 'docs', 'completion-mapping.md').read_text(encoding='utf-8')
        self.assertEqual(text, gen_mapping.generate())
        for item in load_base(SLUG)['items']:
            self.assertIn(f'| `{item["id"]}` |', text)
        self.assertEqual(sum(1 for line in text.splitlines() if line.startswith('| `')), 32)

    def test_rendered_page_in_headless_browser(self):
        node, root = shutil.which('node'), subprocess.run(['npm', 'root', '-g'], capture_output=True, text=True).stdout.strip() if shutil.which('npm') else ''
        if not node or not root or not Path(root, 'playwright').exists():
            self.skipTest('playwright 없음')
        data, _ = build_with(PROJECT, gen_mapping.codex_report)
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, 'p.html')
            build.render(data, out)
            script = Path(tmp, 'dom.js')
            script.write_text("""const { chromium } = require('playwright');
(async()=>{const b=await chromium.launch();const p=await b.newPage();
await p.goto('file://'+process.argv[2]);await p.waitForTimeout(600);
const r=await p.evaluate(()=>({count:document.getElementById('countB').textContent,
 partial:[...document.querySelectorAll('.fnode.partial')].map(n=>n.dataset.id),
 summary:document.getElementById('completionSummary').innerText,
 doneReq:[...document.querySelectorAll('.fnode.done')].length}));
console.log(JSON.stringify(r));await b.close();})();""", encoding='utf-8')
            res = subprocess.run([node, str(script), out], capture_output=True, text=True, env=dict(os.environ, NODE_PATH=root), timeout=90)
        self.assertEqual(res.returncode, 0, res.stderr[-500:])
        info = json.loads(res.stdout.strip().splitlines()[-1])
        self.assertEqual(info['count'], '7/13')
        self.assertEqual(sorted(info['partial']), sorted(i['id'] for i in data['items'] if i.get('completion', {}).get('status') == 'partial'))
        self.assertIn('하위 조건 완료', info['summary'])
        self.assertIn('자동으로 완료가 된다', info['summary'])


if __name__ == '__main__':
    unittest.main()
