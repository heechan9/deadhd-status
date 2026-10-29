"""카드에 연결된 PR 의 Draft·병합 여부·CI 가 실제 GitHub 응답을 따라가는지, 오래됨·실패가 보이는지,
그리고 필수 집계·countScope 가 PR 병합·CI 만으로 바뀌지 않는지 확인한다. 네트워크를 쓰지 않는다.
카드 state 는 completion 규칙이 허용한 코드 반영 카드(AUTO_STATE)에서만 바뀔 수 있다(test_completion.py 가 상세 검증)."""
import copy
import json
import os
import tempfile
import unittest
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import build

AT = datetime(2026, 10, 27, 15, 40, tzinfo=build.KST)
SHA_A, SHA_B = 'a' * 40, 'b' * 40
FROZEN = ('countScope', 'countScopeReason', 'badge', 'label', 'title', 'lane', 'id')
AUTO_STATE = {'draft-work'}   # 연결 PR 이 전부 main 에 병합됐을 때만 state 가 바뀔 수 있는 코드 반영 카드


def run(name, status='completed', conclusion='success', event='pull_request', at='2026-10-27T05:00:00Z'):
    return {'name': name, 'status': status, 'conclusion': conclusion, 'event': event, 'created_at': at,
            'html_url': f'https://github.com/x/y/actions/runs/{abs(hash(name + at)) % 10**8}'}


def pull(number, state='open', draft=True, merged_at=None, head=SHA_A):
    return {'number': number, 'title': f'PR {number}', 'html_url': f'https://github.com/heechan9/bunkering-ai/pull/{number}',
            'state': state, 'draft': draft, 'merged_at': merged_at, 'merge_commit_sha': 'd' * 40,
            'head': {'sha': head}, 'base': {'ref': 'main'}, 'updated_at': '2026-10-27T05:00:00Z'}


def pr_record(number, repo='heechan9/bunkering-ai', state='open', draft=True, merged=False, ci=None, head=SHA_A):
    return {'repo': repo, 'n': number, 'title': f'PR {number}', 'url': f'https://github.com/{repo}/pull/{number}',
            'state': state, 'draft': draft, 'merged': merged, 'mergedAt': '2026-10-27T05:00:00Z' if merged else None,
            'mergeSha': 'ddddddd' if merged else '', 'headSha': head, 'baseRef': 'main',
            'updatedAt': '2026-10-27T05:00:00Z', 'ci': ci or []}


def ci(name='Python regression', status='completed', conclusion='success'):
    return {'name': name, 'status': status, 'conclusion': conclusion, 'url': 'https://github.com/x/y/actions/runs/1',
            'event': 'pull_request', 'at': '2026-10-27T05:00:00Z'}


def router(routes):
    def fake_get(path):
        for prefix, value in routes.items():
            if path.startswith(prefix):
                if isinstance(value, Exception):
                    raise value
                return value
        raise AssertionError('예상 밖 요청: ' + path)
    return fake_get


def repo_stub(spec, base):
    sha = base['curatedRefs'][spec['id']] if 'curatedRefs' in base else base['curatedSha']
    prs = [r for r in base.get('curatedPrs', []) if r['repo'] == spec['repo']]
    return dict(repo=spec['repo'], branch='main', html='https://github.com/' + spec['repo'],
                head=dict(sha=sha, date='2026-10-27T05:00:00Z', title='t', url='https://github.com/' + spec['repo'] + '/commit/' + sha),
                ci=[], merged=[], open=[dict(n=r['number'], title='t', url='https://github.com/%s/pull/%d' % (r['repo'], r['number']), draft=True, headSha=r['sha'], baseSha='0' * 40) for r in prs])


def load_base(slug):
    return json.loads((Path(build.ROOT) / 'content' / (slug + '.base.json')).read_text(encoding='utf-8'))


def build_with(project, pr_factory, at=AT, prev=None, curated_at=None):
    base = load_base(project['slug'])
    if curated_at:
        orig = build.json.load

        def patched(fh):
            data = orig(fh)
            data['curatedAt'] = curated_at
            return data
    with patch.object(build, 'fetch_repo', side_effect=lambda spec: repo_stub(spec, base)), \
            patch.object(build, 'fetch_pr', side_effect=pr_factory):
        if curated_at:
            with patch.object(build.json, 'load', side_effect=patched):
                return build.build_project(project, prev or {}, at)
        return build.build_project(project, prev or {}, at)


class FetchPr(unittest.TestCase):
    def test_open_draft_in_progress(self):
        routes = {'repos/o/r/pulls/7': pull(7), 'repos/o/r/actions/runs': {'workflow_runs': [run('CI', 'in_progress', None)]}}
        with patch.object(build, 'get', side_effect=router(routes)):
            r = build.fetch_pr('o/r', 7)
        self.assertEqual((r['state'], r['draft'], r['merged']), ('open', True, False))
        self.assertEqual(build.ci_state(r['ci'])[0], 'side')
        self.assertIn('열림·Draft', build.pr_state_word(r))
        self.assertIn('실행 중', build.pr_ci_word(r))

    def test_merged_success_uses_latest_run_per_workflow(self):
        runs = [run('CI', conclusion='failure', at='2026-10-27T01:00:00Z'), run('CI', conclusion='success', at='2026-10-27T02:00:00Z')]
        routes = {'repos/o/r/pulls/8': pull(8, 'closed', False, '2026-10-17T12:36:43Z'), 'repos/o/r/actions/runs': {'workflow_runs': runs}}
        with patch.object(build, 'get', side_effect=router(routes)):
            r = build.fetch_pr('o/r', 8)
        self.assertTrue(r['merged'])
        self.assertEqual(r['mergeSha'], 'ddddddd')
        self.assertEqual(len(r['ci']), 1)
        self.assertTrue(build.pr_state_word(r).startswith('병합됨 2026-10-17 21:36 KST'))
        self.assertIn('성공', build.pr_ci_word(r))

    def test_closed_unmerged_and_failure_and_no_runs(self):
        routes = {'repos/o/r/pulls/9': pull(9, 'closed', False, None), 'repos/o/r/actions/runs': {'workflow_runs': [run('CI', conclusion='failure')]}}
        with patch.object(build, 'get', side_effect=router(routes)):
            r = build.fetch_pr('o/r', 9)
        self.assertEqual(build.pr_state_word(r), '닫힘(미병합)')
        self.assertIn('실패 CI', build.pr_ci_word(r))
        routes['repos/o/r/actions/runs'] = {'workflow_runs': []}
        with patch.object(build, 'get', side_effect=router(routes)):
            r = build.fetch_pr('o/r', 9)
        self.assertIn('실행 기록 없음', build.pr_ci_word(r))  # 기록 없음 ≠ 성공


class LinkedPrs(unittest.TestCase):
    def test_derived_from_evidence_and_deduped(self):
        item = {'id': 'x', 'evidence': [
            {'text': 'a', 'href': 'https://github.com/heechan9/bunkering-ai/pull/146'},
            {'text': 'b', 'href': 'https://github.com/heechan9/bunkering-ai/pull/146/'},
            {'text': 'run', 'href': 'https://github.com/heechan9/bunkering-ai/actions/runs/1'},
            {'text': 'issue', 'href': 'https://github.com/heechan9/bunkering-ai/issues/5'},
            {'text': 'nolink'}]}
        self.assertEqual(build.linked_prs(item), [('heechan9/bunkering-ai', 146)])

    def test_explicit_overrides_and_opt_out(self):
        item = {'id': 'x', 'linkedPrs': ['o/r#1', {'repo': 'o/s', 'number': 2}],
                'evidence': [{'text': 'a', 'href': 'https://github.com/o/r/pull/99'}]}
        self.assertEqual(build.linked_prs(item), [('o/r', 1), ('o/s', 2)])
        self.assertEqual(build.linked_prs(dict(item, liveStatus=False)), [])
        with self.assertRaises(ValueError):
            build.linked_prs({'id': 'x', 'linkedPrs': ['not-a-pr']})


class Overlay(unittest.TestCase):
    def make(self):
        return [{'id': 'c', 'label': 'L', 'state': 'left', 'countScope': 'submission', 'badge': 'B', 'sub': 's', 'title': 't',
                 'body': '수동 본문.', 'evidence': [{'text': 'PR #146 · Draft', 'href': 'https://github.com/o/r/pull/146'}]}]

    def test_only_body_and_evidence_text_change(self):
        items = self.make()
        before = copy.deepcopy(items)
        prs = {'o/r#146': {'ok': True, 'fetchedAt': AT.isoformat(), 'data': pr_record(146, 'o/r', 'closed', False, True, [ci()])}}
        self.assertEqual(build.overlay_live(items, prs, AT, 'o/r', {}), 1)
        for key in FROZEN:
            self.assertEqual(items[0].get(key), before[0].get(key))
        self.assertTrue(items[0]['body'].startswith('수동 본문.'))
        self.assertIn('[자동 조회 10-27 15:40 KST] #146 병합됨', items[0]['body'])
        self.assertIn(build.LIVE_NOTE, items[0]['body'])
        self.assertIn('｜자동: 병합됨', items[0]['evidence'][0]['text'])
        self.assertEqual(items[0]['evidence'][0]['href'], before[0]['evidence'][0]['href'])

    def test_status_follows_github_without_promoting(self):
        for rec, expected in [(pr_record(146, 'o/r'), '열림·Draft'),
                              (pr_record(146, 'o/r', draft=False), '열림(Draft 아님)'),
                              (pr_record(146, 'o/r', 'closed', False, True), '병합됨'),
                              (pr_record(146, 'o/r', 'closed', False, False), '닫힘(미병합)')]:
            items = self.make()
            build.overlay_live(items, {'o/r#146': {'ok': True, 'fetchedAt': AT.isoformat(), 'data': rec}}, AT, 'o/r', {})
            self.assertIn(expected, items[0]['body'])
            self.assertEqual(items[0]['state'], 'left')

    def test_head_changed_since_manual_review(self):
        items = self.make()
        prs = {'o/r#146': {'ok': True, 'fetchedAt': AT.isoformat(), 'data': pr_record(146, 'o/r', head=SHA_B)}}
        build.overlay_live(items, prs, AT, 'o/r', {('o/r', 146): SHA_A})
        self.assertIn('수동 검토 head aaaaaaa 이후 변경', items[0]['body'])
        items = self.make()
        build.overlay_live(items, prs, AT, 'o/r', {('o/r', 146): SHA_B})
        self.assertNotIn('이후 변경', items[0]['body'])

    def test_other_repo_pr_is_qualified(self):
        items = [{'id': 'c', 'label': 'L', 'state': 'left', 'body': '', 'evidence': [{'text': 'x', 'href': 'https://github.com/p/q/pull/3'}]}]
        prs = {'p/q#3': {'ok': True, 'fetchedAt': AT.isoformat(), 'data': pr_record(3, 'p/q')}}
        build.overlay_live(items, prs, AT, 'o/r', {})
        self.assertIn('p/q#3 열림·Draft', items[0]['body'])


class FailureAndStaleness(unittest.TestCase):
    def test_failure_keeps_last_success_and_marks_age(self):
        old = AT - timedelta(hours=5)
        prev = {'o/r#1': {'ok': True, 'fetchedAt': old.isoformat(), 'data': pr_record(1, 'o/r', 'closed', False, True, [ci()])}}
        with patch.object(build, 'fetch_pr', side_effect=urllib.error.HTTPError('u', 403, 'rate', {}, None)):
            out = build.refresh_prs([('o/r', 1)], prev, AT)
        e = out['o/r#1']
        self.assertFalse(e['ok'])
        self.assertEqual(e['error'], 'HTTPError 403')
        self.assertEqual(e['fetchedAt'], old.isoformat())     # 마지막 성공 시각 유지
        self.assertEqual(e['data']['merged'], True)
        line = build.pr_line('o/r', 1, e, AT, 'o/r')
        self.assertIn('조회 실패(HTTPError 403)', line)
        self.assertIn('5시간 전 · 오래됨', line)

    def test_recent_failure_is_not_marked_stale_but_is_shown(self):
        recent = AT - timedelta(hours=1)
        e = {'ok': False, 'error': 'URLError', 'fetchedAt': recent.isoformat(), 'data': pr_record(1, 'o/r')}
        line = build.pr_line('o/r', 1, e, AT, 'o/r')
        self.assertIn('조회 실패(URLError)', line)
        self.assertNotIn('오래됨', line)

    def test_failure_without_previous_record(self):
        with patch.object(build, 'fetch_pr', side_effect=OSError('offline')):
            out = build.refresh_prs([('o/r', 1)], {}, AT)
        self.assertFalse(out['o/r#1']['ok'])
        self.assertNotIn('data', out['o/r#1'])
        self.assertIn('조회 실패(OSError) · 이전 성공 기록 없음', build.pr_line('o/r', 1, out['o/r#1'], AT, 'o/r'))
        self.assertIn('조회 실패·이전 기록 없음', build.pr_short(out['o/r#1'], AT))

    def test_limit_exceeded_is_reported(self):
        with patch.object(build, 'MAX_LINKED_PRS', 1), patch.object(build, 'fetch_pr', side_effect=lambda r, n: pr_record(n, r)):
            out = build.refresh_prs([('o/r', 1), ('o/r', 2)], {}, AT)
        self.assertTrue(out['o/r#1']['ok'])
        self.assertEqual(out['o/r#2']['error'], '조회 상한 초과')

    def test_parse_kst(self):
        self.assertEqual(build.parse_kst('2026-10-27 14:57 KST'), datetime(2026, 10, 27, 14, 57, tzinfo=build.KST))
        self.assertIsNone(build.parse_kst('어제 오후'))
        self.assertIsNone(build.parse_kst('2026-10-27T14:57:00'))   # 시차 없는 시각은 근거로 쓰지 않는다
        self.assertIsNone(build.parse_kst(None))


class BuildProject(unittest.TestCase):
    def frozen(self, data, base):
        got = {i['id']: i for i in data['items']}
        for item in base['items']:
            for key in FROZEN:
                self.assertEqual(got[item['id']].get(key), item.get(key), (item['id'], key))
            if item['id'] not in AUTO_STATE:
                self.assertEqual(got[item['id']]['state'], item['state'], (item['id'], 'state'))
            self.assertTrue((got[item['id']].get('sub') or '').startswith(item.get('sub') or ''), item['id'])
        self.assertNotIn('linkedPrs', json.dumps(data))
        self.assertNotIn('liveStatus', json.dumps(data))

    def test_best_case_never_changes_required_count_or_scopes(self):
        """모든 PR 이 병합되고 CI 가 성공해도 필수 집계·countScope 는 그대로이고, state 는 허용된 코드 반영 카드만 바뀔 수 있다."""
        for project in build.PROJECTS:
            base = load_base(project['slug'])
            good = lambda repo, n: pr_record(n, repo, 'closed', False, True, [ci()])
            data, _ = build_with(project, good)
            self.frozen(data, base)
            required = [i for i in data['items'] if i.get('countScope') == 'submission']
            expected = [i for i in base['items'] if i.get('countScope') == 'submission']
            self.assertEqual(sum(i['state'] == 'done' for i in required), sum(i['state'] == 'done' for i in expected))
            self.assertEqual(len(required), len(expected))

    def test_worst_case_never_changes_card_states_either(self):
        for project in build.PROJECTS:
            base = load_base(project['slug'])
            bad = lambda repo, n: pr_record(n, repo, 'closed', False, False, [ci(conclusion='failure')])
            data, _ = build_with(project, bad)
            self.frozen(data, base)
            got = {i['id']: i for i in data['items']}
            for item in base['items']:      # 닫힘·실패는 어떤 카드도 완료로 만들거나 되돌리지 않는다
                self.assertEqual(got[item['id']]['state'], item['state'], item['id'])

    def test_cards_follow_github_between_builds(self):
        project = build.PROJECTS[0]
        d1, s1 = build_with(project, lambda repo, n: pr_record(n, repo, draft=True, ci=[ci(status='in_progress', conclusion=None)]))
        d2, s2 = build_with(project, lambda repo, n: pr_record(n, repo, 'closed', False, True, [ci()]))
        c1 = {i['id']: i for i in d1['items']}['draft-work']['body']
        c2 = {i['id']: i for i in d2['items']}['draft-work']['body']
        self.assertIn('#146 열림·Draft', c1)
        self.assertIn('실행 중', c1)
        self.assertIn('#146 병합됨', c2)
        self.assertNotIn('#146 열림·Draft', c2)
        self.assertEqual(set(s1['prs']), set(s2['prs']))
        self.assertTrue(all(e['ok'] for e in s2['prs'].values()))

    def test_failures_are_visible_on_page_and_state(self):
        project = build.PROJECTS[0]
        data, state = build_with(project, urllib.error.URLError('down'))
        ids = [i['id'] for i in data['items']]
        self.assertIn('pr-live-failed', ids)
        failed = {i['id']: i for i in data['items']}['pr-live-failed']
        self.assertEqual(failed['state'], 'blocked')
        self.assertNotIn('countScope', failed)               # 필수 집계에 들어가지 않는다
        self.assertTrue(all(not e['ok'] for e in state['prs'].values()))
        self.assertIn('일부 실패', data['meta'][0])
        self.assertTrue(any('카드 연결 PR 조회 0/' in m for m in data['meta'] if isinstance(m, str)))
        body = {i['id']: i for i in data['items']}['draft-work']['body']
        self.assertIn('조회 실패', body)
        self.assertIn('이전 성공 기록 없음', body)

    def test_stale_previous_success_is_kept_and_flagged(self):
        project = build.PROJECTS[0]
        d_ok, s_ok = build_with(project, lambda repo, n: pr_record(n, repo, 'closed', False, True, [ci()]), at=AT - timedelta(hours=6))
        d, s = build_with(project, OSError('offline'), prev={project['slug']: s_ok})
        body = {i['id']: i for i in d['items']}['draft-work']['body']
        self.assertIn('#146 병합됨', body)                    # 직전 성공 기록을 유지
        self.assertIn('6시간 전 · 오래됨', body)
        self.assertTrue(all(not e['ok'] and e['data'] for e in s['prs'].values()))

    def test_curated_review_stale_banner(self):
        project = build.PROJECTS[0]
        d, _ = build_with(project, lambda repo, n: pr_record(n, repo))
        self.assertNotIn('curated-stale', [i['id'] for i in d['items']])
        d, _ = build_with(project, lambda repo, n: pr_record(n, repo), at=AT + timedelta(days=7))
        item = {i['id']: i for i in d['items']}['curated-stale']
        self.assertNotIn('countScope', item)
        self.assertIn('다시 검토', item['body'])
        self.assertTrue(any(isinstance(m, str) and m.startswith('수동 내용 검토 시각') and '오래됨' in m for m in d['meta']))

    def test_unparseable_curated_time_is_flagged(self):
        project = build.PROJECTS[0]
        d, _ = build_with(project, lambda repo, n: pr_record(n, repo), curated_at='어제')
        item = {i['id']: i for i in d['items']}['curated-stale']
        self.assertEqual(item['sub'], '시각 해석 불가')

    def test_every_live_card_has_disclaimer_and_no_completion_claim(self):
        for project in build.PROJECTS:
            data, _ = build_with(project, lambda repo, n: pr_record(n, repo, 'closed', False, True, [ci()]))
            live = [i for i in data['items'] if '[자동 조회 ' in (i.get('body') or '')]
            self.assertTrue(live)
            for item in live:
                self.assertIn(build.LIVE_NOTE, item['body'])
                self.assertIn('본인 확인', item['body'])
                self.assertIn('계약 채택', item['body'])
                self.assertIn('최종 제출', item['body'])

    def test_pr_drift_item_explains_current_state(self):
        project = build.PROJECTS[0]
        base = load_base(project['slug'])
        with patch.object(build, 'fetch_repo', side_effect=lambda spec: dict(repo_stub(spec, base), open=[])), \
                patch.object(build, 'fetch_pr', side_effect=lambda repo, n: pr_record(n, repo, 'closed', False, True, [ci()])):
            data, _ = build.build_project(project, {}, AT)
        drift = [i for i in data['items'] if i['id'].startswith('pr-drift-')]
        self.assertTrue(drift)
        self.assertTrue(all('현재 자동 조회:' in i['body'] and '병합됨' in i['body'] for i in drift))
        self.assertTrue(all(i['state'] == 'side' for i in drift))


class RenderAndPlumbing(unittest.TestCase):
    def test_rendered_page_shows_live_and_failure_text(self):
        project = build.PROJECTS[0]
        data, _ = build_with(project, urllib.error.URLError('down'))
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, 'p.html')
            build.render(data, out)
            html = Path(out).read_text(encoding='utf-8')
        self.assertIn('[자동 조회 ', html)
        self.assertIn('조회 실패', html)
        self.assertIn('PR 상태 갱신 실패', html)

    def test_main_reports_failure_when_only_prs_fail(self):
        project = build.PROJECTS[0]
        base = load_base(project['slug'])
        with tempfile.TemporaryDirectory() as tmp, patch.object(build, 'SITE', tmp), \
                patch.object(build, 'PROJECTS', [project]), patch.object(build, 'load_previous_state', return_value={}), \
                patch.object(build, 'fetch_repo', side_effect=lambda spec: repo_stub(spec, base)), \
                patch.object(build, 'fetch_pr', side_effect=OSError('offline')):
            build.main()
            index = Path(tmp, 'index.html').read_text(encoding='utf-8')
            state = json.loads(Path(tmp, 'state.json').read_text(encoding='utf-8'))
        self.assertIn('일부 조회 실패', index)
        self.assertIn('prs', state[project['slug']])

    def test_content_has_valid_link_specs(self):
        for project in build.PROJECTS:
            for item in load_base(project['slug'])['items']:
                build.linked_prs(item)      # 형식 오류면 ValueError


if __name__ == '__main__':
    unittest.main()
