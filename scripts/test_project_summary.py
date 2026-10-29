"""Current project counts are evidence categories, not weighted global completion."""
import json
import unittest
from pathlib import Path
from test_live_status import build_with
from test_completion import PROJECT, by_id, tally

ROOT=Path(__file__).resolve().parents[1]

class CurrentProjectSummary(unittest.TestCase):
    def test_counts_and_evidence_boundaries(self):
        base=json.loads((ROOT/'content/bunkering-ai.base.json').read_text())
        s=base['currentProjectSummary']; groups=s['groups']
        self.assertEqual([g['id'] for g in groups],['development','artifacts','submission'])
        counts=[(sum(i['state']=='done' for i in g['items']),len(g['items'])) for g in groups]
        self.assertEqual(counts,[(3,3),(2,2),(0,3)])
        ids=[i['id'] for g in groups for i in g['items']]
        self.assertEqual(len(ids),len(set(ids)))
        self.assertNotIn('accept',ids)
        self.assertNotIn('submission-final-paper',ids)
        for g in groups:
            for i in g['items']:
                self.assertIn(i['state'],('done','unverified'))
                self.assertTrue(i['detail']); self.assertTrue(i['evidence'])
        self.assertTrue(all(i['state']=='unverified' for i in groups[2]['items']))
        self.assertIn('미확인은 미수행을 뜻하지 않습니다',s['note'])
        self.assertIn('제작 완료와 최종 제출 가능·접수 완료는 다릅니다',s['note'])
        self.assertIn('40738098873',json.dumps(groups[0]))
        self.assertIn('990 passed',str(groups[0]))
        self.assertIn('연속 녹화가 아니며',str(groups[1]))
        self.assertIn('전달 기록',str(groups[1]))
        self.assertNotIn('chatgpt.com/api/library',str(s))
        self.assertNotIn('libfile_',str(s))

    def test_history_not_relabelled_as_new_success(self):
        data,_=build_with(PROJECT,OSError('offline'))
        cards=by_id(data)
        self.assertIn('currentProjectSummary',data)
        self.assertEqual(tally(data),(7,13)) # historical card tally, not current project ratio
        self.assertIn('과거 기록',cards['submission-team-intake']['title'])
        self.assertIn('최신 팀원 작업 미완료로 해석하지 않습니다',cards['submission-team-intake']['body'])
        for key in ('submission-project-report','submission-video','n-web'):
            self.assertNotEqual(cards[key]['state'],'done')
        self.assertEqual(cards['c-ulsan']['state'],'blocked')
        self.assertEqual([i['state'] for i in data['currentProjectSummary']['groups'][2]['items']],['unverified']*3)

    def test_rendered_summary_in_all_views_without_global_completion_ratio(self):
        import tempfile
        import build
        data,_=build_with(PROJECT,OSError('offline'))
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp,'page.html');build.render(data,str(out)); html=out.read_text()
        self.assertIn('id="projectSummary"',html)
        for label, ratio in [('개발·통합·배포 확인','3/3'),('보고서·영상 제작 확인','2/2'),('제출 절차 확인','0/3')]:
            self.assertIn(label+' <b>'+ratio+'</b>',html)
        self.assertNotIn('<b>${requiredDone}/${requiredTotal}</b>',html)
        self.assertNotIn("$('countB').textContent = requiredDone + '/' + requiredTotal",html)
        self.assertIn('.progress,#tally,#completionSummary,.cx-count,.cx-bar,.cc-ring,.cc-seg{display:none!important}',html)
        self.assertLess(html.index('id="projectSummary"'),html.index('<div id="compact"'))
        self.assertIn('미확인은 미수행을 뜻하지 않습니다',html)
        self.assertIn('과거 판정을 보존한 이력',html)

    def test_summary_escapes_untrusted_labels_and_links(self):
        import copy
        import build
        summary=copy.deepcopy(json.loads((ROOT/'content/bunkering-ai.base.json').read_text())['currentProjectSummary'])
        summary['title']='<img src=x onerror=alert(1)>'
        summary['groups'][0]['items'][0]['evidence']=[{'label':'<b>bad</b>','href':'javascript:alert(1)'}]
        html=build.project_summary_html(summary)
        self.assertIn('&lt;img',html)
        self.assertNotIn('href="javascript:',html)
        self.assertIn('&lt;b&gt;bad&lt;/b&gt;',html)

if __name__=='__main__':unittest.main()
