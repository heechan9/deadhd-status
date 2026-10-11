import copy
import unittest
from unittest.mock import patch
import build

class ReviewTracking(unittest.TestCase):
    def test_review_drift_and_failure(self):
        project=build.PROJECTS[1]
        import json
        from pathlib import Path
        base=json.loads((Path(build.ROOT)/'content/adversarial-ai.base.json').read_text())
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
        self.assertEqual(sum('drift' in i['id'] for i in data['items']),4)
        with patch.object(build,'fetch_repo',side_effect=OSError('offline')):
            data,_=build.build_project(project,{'adversarial-ai':state},build.now_kst())
        self.assertEqual(sum(i['id'].endswith('-fail') for i in data['items']),2)
        self.assertFalse(any('drift' in i['id'] for i in data['items']))

if __name__=='__main__':unittest.main()
