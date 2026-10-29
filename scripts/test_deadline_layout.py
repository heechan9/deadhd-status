"""Current deadlines and historical obligations must not share the lead lane."""
import tempfile
import unittest
from pathlib import Path
import build
from test_completion import by_id, tally, PROJECT
from test_live_status import build_with, load_base


class DeadlineLayout(unittest.TestCase):
    def test_current_submission_leads_and_ack_remains_unconfirmed(self):
        base = load_base('bunkering-ai')
        self.assertEqual(base['items'][0]['id'], 'submission-project-report')
        self.assertIn('10/31', base['lanes'][0])
        data, _ = build_with(PROJECT, OSError('offline'))
        cards = by_id(data)
        self.assertEqual(cards['submission-project-report']['lane'], 0)
        for cid in ('submission-final-paper', 'submission-video'):
            card = cards[cid]
            self.assertGreater(card['lane'], 0)
            self.assertIn('지난 ACK 마감', base['lanes'][card['lane']])
            self.assertIn('지난 마감', card['label'])
            self.assertIn('미확인', card['sub'])
            self.assertNotEqual(card['state'], 'done')
            self.assertEqual(card['countScope'], 'submission')
        self.assertEqual(tally(data), (7, 13))
        self.assertEqual(len(base['items']), 32)
        self.assertIn('업데이트 날짜가 아니며', base['goal'])
        self.assertEqual(base['curatedAt'], '2026-10-29 13:58 KST')

    def test_intrinsic_layout_survives_render_on_both_projects(self):
        for project in build.PROJECTS:
            with self.subTest(project=project['slug']):
                data, _ = build_with(project, OSError('offline'))
                with tempfile.TemporaryDirectory() as tmp:
                    out = Path(tmp, 'status.html')
                    build.render(data, str(out))
                    html = out.read_text()
                self.assertIn("canvasEl.classList.add('responsive-timeline')", html)
                self.assertIn('grid-template-columns: minmax(0, 1fr)', html)
                self.assertIn('overflow-wrap: anywhere', html)
                self.assertNotIn('band.style.height =', html)
                self.assertNotIn('canvasEl.style.width =', html)
                self.assertIn('new ResizeObserver(scheduleEdges)', html)
                self.assertIn("svg.setAttribute('class', 'edges')", html)
                self.assertIn("flow.setAttribute('class', 'edge-flow')", html)


if __name__ == '__main__':
    unittest.main()
