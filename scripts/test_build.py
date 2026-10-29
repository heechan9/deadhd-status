import copy
import unittest
from unittest.mock import patch
import build

def offline_pr(repo, number):
    """네트워크 없이 쓰는 연결 PR 조회 대체값(열림·Draft·CI 기록 없음)."""
    return dict(repo=repo, n=number, title='stub', url=f'https://github.com/{repo}/pull/{number}', state='open',
                draft=True, merged=False, mergedAt=None, mergeSha='', headSha='c' * 40, baseRef='main',
                updatedAt='2026-10-27T00:00:00Z', ci=[])


class ReviewTracking(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(build, 'fetch_pr', side_effect=offline_pr)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_review_drift_and_failure(self):
        project=build.PROJECTS[1]
        import json
        from pathlib import Path
        base=json.loads((Path(build.ROOT)/'content/adversarial-ai.base.json').read_text(encoding='utf-8'))
        def fetch(spec):
            sha=base['curatedRefs'][spec['id']]
            return dict(repo=spec['repo'],branch='main',head=dict(sha=sha,date='2026-10-09T00:00:00Z',title='test',url='https://github.com/'+spec['repo']+'/commit/'+sha),ci=[],merged=[],open=[dict(n=r['number'],title='review',url='https://github.com/'+r['repo']+'/pull/'+str(r['number']),draft=True,headSha=r['sha']) for r in base['curatedPrs'] if r['repo']==spec['repo']])
        with patch.object(build,'fetch_repo',side_effect=fetch):
            data,state=build.build_project(project,{},build.now_kst())
        self.assertFalse(any('drift' in i['id'] for i in data['items']))

        self.assertEqual(state['curatedRefs'],base['curatedRefs'])
        def changed(spec):
            f=fetch(spec); f['head']['sha']='a'*40
            for p in f['open']:p['headSha']='b'*40
            return f
        with patch.object(build,'fetch_repo',side_effect=changed):
            data,_=build.build_project(project,{},build.now_kst())
        self.assertEqual(sum('drift' in i['id'] for i in data['items']),len(base['curatedRefs'])+len(base['curatedPrs']))
        with patch.object(build,'fetch_repo',side_effect=OSError('offline')):
            data,_=build.build_project(project,{'adversarial-ai':state},build.now_kst())
        self.assertEqual(sum(i['id'].endswith('-fail') for i in data['items']),2)
        self.assertFalse(any('drift' in i['id'] for i in data['items']))

    def test_research_and_submission_boundaries(self):
        import json
        from pathlib import Path
        for project in (p for p in build.PROJECTS if p['slug'] in ('bunkering-ai', 'adversarial-ai')):
            with self.subTest(project=project['slug']):
                base=json.loads((Path(build.ROOT)/('content/'+project['slug']+'.base.json')).read_text(encoding='utf-8'))
                items={i['id']:i for i in base['items']}
                self.assertEqual(items['accept']['state'], 'done')
                self.assertNotIn('href', items['accept']['evidence'][0])
                for key in ('submission-final-paper','submission-video','submission-project-report','submission-team-intake'):
                    self.assertEqual(items[key]['state'], 'left')
                    self.assertEqual(items[key]['lane'], 6 if project['slug'] == 'bunkering-ai' and key in ('submission-final-paper', 'submission-video') else 0)
                self.assertTrue(all(s['lane'] > 0 for s in project['repos']))
                self.assertEqual(len(items),len(base['items']))
                self.assertIn('전체 완료율로 합산하지 않습니다' if project['slug']=='bunkering-ai' else '이번 최종제출 필수 항목만 집계', base['goal'])
                for item in items.values():
                    self.assertIn(item['countScope'], ('submission','after-submission','reference'))
                    self.assertTrue(item['countScopeReason'])
                self.assertTrue(all(items[k]['countScope']=='submission' for k in
                                    ('accept','submission-final-paper','submission-video','submission-project-report')))
                if project['slug']=='bunkering-ai':
                    self.assertEqual(items['wait']['state'], 'blocked')
                    self.assertEqual(items['c-ulsan']['state'], 'blocked')
                    self.assertEqual(items['n-web']['state'], 'left')
                    self.assertEqual(items['c-ulsan']['countScope'],'submission')
                    self.assertEqual(items['local-integration-extension']['countScope'],'after-submission')
                    self.assertEqual(items['fair']['countScope'],'after-submission')
                    self.assertEqual(items['current-ci-snapshot']['countScope'],'reference')
                else:
                    self.assertEqual(items['verify']['state'], 'blocked')
                    self.assertEqual(items['gate']['state'], 'side')
                    self.assertEqual(items['iterative-gpu']['state'], 'side')
                    self.assertEqual(items['verify']['countScope'],'submission')
                    self.assertEqual(items['disc']['countScope'],'submission')
                    self.assertTrue(all(items[k]['countScope']=='after-submission' for k in
                                        ('cnn-train','square','surfree','iterative-gpu','bim-environment-comparison')))

if __name__=='__main__':unittest.main()

