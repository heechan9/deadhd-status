"""FabGuard evidence is neither a submission contract nor real-robot validation."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import build
from test_live_status import build_with, load_base, pr_record, repo_stub

class FabGuardEvidence(unittest.TestCase):
    def setUp(self):
        self.project=next(p for p in build.PROJECTS if p['slug']=='fabguard-ai')
        self.base=load_base('fabguard-ai')

    def test_registration_and_evidence_only_scope(self):
        self.assertEqual(len(build.PROJECTS),3)
        self.assertIn('fabguard-ai.html',build.INDEX)
        self.assertTrue(self.base['evidenceOnly'])
        self.assertEqual(self.base['curatedSha'],'cce8360fba1920fa8465da79dbd3b35cee2c4ae8')
        self.assertTrue(all(i['countScope']=='reference' for i in self.base['items']))
        self.assertEqual(len({i['id'] for i in self.base['items']}),len(self.base['items']))

    def test_synthetic_draft_and_field_boundaries_survive_merges(self):
        data,_=build_with(self.project,lambda repo,n:pr_record(n,repo,state='closed',draft=False,merged=True))
        cards={i['id']:i for i in data['items']}
        self.assertEqual(cards['r01-3d']['state'],'done')
        self.assertEqual(cards['ur3-replay-draft']['state'],'side')
        self.assertEqual(cards['offline-report-draft']['state'],'side')
        self.assertEqual(cards['field-validation']['state'],'blocked')
        self.assertIn('실제 동작 3D 재현',cards['ur3-replay-draft']['body'])
        self.assertIn('null',cards['field-validation']['body'])
        self.assertIn('새로 렌더 검사한 것은 아니다',cards['release-render-evidence']['body'])
        self.assertEqual({r['number'] for r in self.base['curatedPrs']},{178,179,180,181,182})

    def test_fresh_heads_and_failure_are_not_render_qa(self):
        with patch.object(build,'fetch_repo',side_effect=lambda spec:repo_stub(spec,self.base)), patch.object(build,'fetch_pr',side_effect=OSError('offline')):
            data,state=build.build_project(self.project,{},build.now_kst())
        self.assertFalse(any(i['id'].startswith('drift-') for i in data['items']))
        self.assertTrue(any(not p['ok'] for p in state['prs'].values()))
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp,'status.html');build.render(data,str(out));html=out.read_text()
        self.assertIn('id="evidence-only-style"',html)
        self.assertIn('제출 완료율·연구 완성률은 집계하지 않습니다',html)
        self.assertIn('body[data-view] main{display:block!important}',html)
        self.assertIn('실제 휴대전화',html)
        self.assertIn('3D 형상 출처',html)

if __name__=='__main__':unittest.main()
