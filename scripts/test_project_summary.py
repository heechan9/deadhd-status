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
        self.assertIn('비공개 검토·전달 기록 기준', groups[1]['note'])
        self.assertIn('보고서 제작 당시 별도 Claude 검토 기록', groups[1]['items'][0]['detail'])
        self.assertIn('열거한 3개 항목 기준', groups[0]['note'])
        self.assertIn('공개 URL 자체는 사이트 존재 근거', groups[0]['items'][2]['detail'])

    def test_history_not_relabelled_as_new_success(self):
        data,_=build_with(PROJECT,OSError('offline'))
        cards=by_id(data)
        self.assertIn('currentProjectSummary',data)
        self.assertEqual(tally(data),(9,13)) # historical card tally, not current project ratio
        self.assertIn('과거 기록',cards['submission-team-intake']['title'])
        self.assertIn('최신 팀원 작업 미완료로 해석하지 않습니다',cards['submission-team-intake']['body'])
        for key in ('submission-project-report','n-web'):
            self.assertNotEqual(cards[key]['state'],'done')
        self.assertEqual(cards['c-ulsan']['state'],'blocked')
        self.assertEqual([i['state'] for i in data['currentProjectSummary']['groups'][2]['items']],['unverified']*3)

    def test_evidence_summary_supplements_original_scoped_checklist(self):
        import tempfile
        import build
        data,_=build_with(PROJECT,OSError('offline'))
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp,'page.html');build.render(data,str(out)); html=out.read_text()
        self.assertIn('id="projectSummary"',html)
        for label, ratio in [('개발·통합·배포 확인','3/3'),('보고서·영상 제작 확인','2/2'),('제출 절차 확인','0/3')]:
            self.assertIn(label+' <b>'+ratio+'</b>',html)
        self.assertIn('<b>${requiredDone}/${requiredTotal}</b>',html)
        self.assertIn("$('countB').textContent = requiredDone + '/' + requiredTotal",html)
        self.assertNotIn('.progress,#tally,#completionSummary,.cx-count,.cx-bar,.cc-ring,.cc-seg{display:none!important}',html)
        self.assertEqual(html.count('data-checklist-id='),13)
        self.assertIn('최신 개발 통합이 빠졌다는 뜻이 아닙니다',html)
        checklist=build.checklist_html(data['items'])
        self.assertEqual(checklist.count(' · 확인 완료'),9)
        self.assertNotIn('작업 미완료',checklist)
        self.assertIn('기존 체크리스트 확인 완료',html)
        self.assertLess(html.index('id="projectSummary"'),html.index('<div id="compact"'))
        self.assertIn('미확인은 미수행을 뜻하지 않습니다',html)
        self.assertIn('체크리스트에는 지난 ACK 일정·접수 이력이 포함',html)

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
