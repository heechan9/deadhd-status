"""Restored user-confirmed ACK events do not claim institutional verification."""
import unittest
from test_live_status import build_with, load_base
from test_completion import PROJECT, by_id, tally, load_spec

class AckUserConfirmation(unittest.TestCase):
    def test_two_original_milestones_confirmed_without_changing_denominator(self):
        data,_=build_with(PROJECT,OSError('offline'))
        cards=by_id(data)
        self.assertEqual(tally(data),(9,13))
        for cid in ('submission-final-paper','submission-video'):
            self.assertEqual(cards[cid]['state'],'done')
            self.assertEqual(cards[cid]['completion']['status'],'complete')
            self.assertIn('사용자 확인', cards[cid]['label'])
            self.assertEqual(cards[cid]['countScope'],'submission')
        for cid in ('submission-project-report','submission-team-intake','n-web','c-ulsan'):
            self.assertNotEqual(cards[cid]['state'],'done')

    def test_unknown_format_receipt_payment_preserved_outside_event_criteria(self):
        cards=load_spec()['cards']
        for cid in ('submission-final-paper','submission-video'):
            self.assertTrue(all(s['rule']['status']=='done' for s in cards[cid]['subtasks']))
            self.assertTrue(all(s['rule']['status']=='left' for s in cards[cid]['milestones']))
            self.assertEqual(cards[cid]['evidenceLevel'],'curated-only')
        self.assertIn('제출 여부 확인',cards['submission-video']['criterion'])
        self.assertEqual(len(cards['submission-video']['subtasks']),1)
        self.assertEqual(len(cards['submission-final-paper']['subtasks']),2)

    def test_no_private_identifiers_or_stale_ack_unknowns(self):
        base=load_base('bunkering-ai'); text=str(base)
        for secret in ('Sentinel_', 'KIPS_C2026B0421', '기호형'):
            self.assertNotIn(secret,text)
        for stale in ('업로드 미확인','최종본 확인 중','최종 논문 제출 여부는 별도 확인 중'):
            self.assertNotIn(stale,text)
        self.assertIn('2026-10-18 KST',text)
        self.assertIn('2026-10-20 KST',text)
        self.assertIn('2026-10-21 KST',text)

if __name__=='__main__':unittest.main()
