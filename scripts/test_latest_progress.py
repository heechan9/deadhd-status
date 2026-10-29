"""Oct 29 bounded progress: preparation/public UI != final acceptance."""
import unittest
from test_completion import by_id, load_spec, tally, PROJECT
from test_live_status import build_with, pr_record, load_base

class LatestProgress(unittest.TestCase):
    def test_known_merges_survive_failure_but_final_acceptance_does_not(self):
        data, _ = build_with(PROJECT, OSError('offline'))
        cards = by_id(data)
        self.assertEqual(cards['draft-work']['completion']['done'], 4)
        self.assertEqual(cards['draft-work']['completion']['total'], 5)
        self.assertEqual(cards['draft-work']['state'], 'side')
        self.assertEqual(tally(data), (7, 13))
        for cid in ('submission-video','submission-project-report','n-web'):
            self.assertNotEqual(cards[cid]['state'], 'done')

    def test_current_merged_fixture_changes_only_code_children(self):
        def current(repo, n):
            result = pr_record(n, repo, state='closed' if n in (126,146,147,148,150) else 'open',
                             draft=n not in (126,146,147,148,150), merged=n in (126,146,147,148,150))
            if n == 126: result['mergeSha'] = '984411c'
            return result
        data, _ = build_with(PROJECT, current)
        cards = by_id(data)
        self.assertEqual(cards['draft-work']['completion']['done'], 4)
        self.assertEqual(cards['submission-research-remaining']['state'], 'done')
        self.assertEqual(tally(data), (7, 13))

    def test_report_and_project_video_do_not_satisfy_ack_or_official_submission(self):
        spec = load_spec()['cards']
        report = spec['submission-project-report']
        subs = {s['id']:s for s in report['subtasks']}
        self.assertEqual(subs['report-15p-draft']['rule']['status'], 'done')
        self.assertIn('18쪽', subs['report-15p-draft']['label'])
        for key in ('report-final-check','report-owner-confirm','report-forms-submit'):
            self.assertEqual(subs[key]['rule']['status'], 'left')
        self.assertTrue(all(s['rule']['status']=='left' for s in spec['submission-video']['subtasks']))
        video = report['milestones'][1]
        self.assertIn('4분 36초', video['label'])
        self.assertIn('YouTube',video['label'])
        self.assertIn('연속 화면 녹화 아님',video['note'])
        self.assertIn('사람 음성 청취',video['note'])

    def test_public_ui_children_preserve_json_mobile_windows_limits(self):
        spec=load_spec()['cards']['n-web']
        self.assertTrue(all(s['rule']['status']=='done' for s in spec['milestones']))
        self.assertEqual([s['rule']['status'] for s in spec['subtasks']], ['done','left','left'])
        notes=' '.join(s.get('note','') for s in spec['milestones'])
        for word in ('JSON', '모바일', 'Windows'):
            self.assertIn(word, notes)
        base=load_base('bunkering-ai')
        self.assertEqual(base['curatedSha'],'df0621c61e28df0e480f4e41a9ffc150454a1cdd')
        self.assertFalse(any(p['number'] in (146,147,148) for p in base['curatedPrs']))

    def test_manuscript_acceptance_and_visible_video_caveats(self):
        import tempfile
        from pathlib import Path
        import build
        data, _ = build_with(PROJECT, OSError('offline'))
        cards = by_id(data)
        review = cards['submission-research-remaining']
        self.assertEqual((review['state'], review['completion']['status']), ('done', 'complete'))
        self.assertEqual((review['completion']['done'], review['completion']['total']), (1, 1))
        self.assertEqual(tally(data), (7, 13))
        self.assertEqual(cards['submission-project-report']['state'], 'left')
        with tempfile.TemporaryDirectory() as tmp:
            output = str(Path(tmp, 'status.html'))
            build.render(data, output)
            html = Path(output).read_text()
        for text in ('실제 UI 정지화면', '연속 화면 녹화가 아니다', '사람 음성 청취 검수는 미확인'):
            self.assertIn(text, cards['submission-project-report']['body'])
            self.assertIn(text, html)

if __name__ == '__main__': unittest.main()
