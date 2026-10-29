import json
from pathlib import Path
from playwright.sync_api import sync_playwright
# Optional browser QA, run explicitly after installing Playwright in your own environment.
# Uses offline test fixtures; does not claim a live GitHub refresh.
root=Path(__file__).resolve().parents[1]
import argparse
parser=argparse.ArgumentParser()
parser.add_argument('--chromium', default='/usr/bin/chromium')
args=parser.parse_args()
import build
from test_live_status import build_with
(root/'qa').mkdir(exist_ok=True)
for project in build.PROJECTS:
 data,_=build_with(project,OSError('offline QA fixture — not a live refresh'))
 build.render(data,str(root/'qa'/f"{project['slug']}.html"))
results=[]
with sync_playwright() as p:
 browser=p.chromium.launch(executable_path=args.chromium,headless=True,args=['--no-sandbox'])
 for slug in ['bunkering-ai','adversarial-ai']:
  for w in [360,390,430,1440]:
   page=browser.new_page(viewport={'width':w,'height':900},device_scale_factor=1)
   errors=[];page.on('pageerror',lambda err:errors.append(str(err)))
   page.goto((root/'qa'/f'{slug}.html').as_uri());page.wait_for_timeout(500)
   result=page.evaluate('''() => {
    const bounds=e=>e.getBoundingClientRect();
    const bands=[...document.querySelectorAll('.lane-band')];
    const overflow=[...document.querySelectorAll('.fnode, .lane-label, .card')].filter(e=>e.scrollWidth>e.clientWidth+1).map(e=>e.className);
    const overlap=bands.flatMap(b=>[...b.querySelectorAll('.fnode,.lane-label')].filter(n=>bounds(n).bottom>bounds(b).bottom+1 || bounds(n).right>bounds(b).right+1).map(n=>n.dataset.id||n.textContent));
    return {viewport:innerWidth, pageWidth:document.documentElement.scrollWidth, overflow, overlap, first:document.querySelector('.fnode')?.dataset.id, nodes:document.querySelectorAll('.fnode').length, edges:document.querySelectorAll('.edges .edge').length, count:document.querySelector('#countB').textContent};
   }''')
   result.update(slug=slug,width=w,errors=errors);results.append(result)
   page.locator('#flow').screenshot(path=str(root/'qa'/f'{slug}-{w}-timeline.png'))
   page.screenshot(path=str(root/'qa'/f'{slug}-{w}-page.png'),full_page=True)
   assert not result['errors'], result
   assert result['pageWidth'] <= w + 1, result
   assert not result['overflow'] and not result['overlap'], result
   assert result['edges'] > 0, result
   if slug == 'bunkering-ai':
    assert result['first'] == 'submission-project-report', result
    assert result['count'] == '7/13', result
   # View toggles, repeated transitions and resize must keep the graph intact.
   for button in page.locator('.viewbar button[data-v]').all():
    button.click()
   page.reload()
   page.set_viewport_size({'width':390 if w==1440 else 1440,'height':900})
   page.set_viewport_size({'width':w,'height':900})
   assert page.locator('.edges .edge').count()>0
   page.close()
 browser.close()
(root/'qa'/'responsive-results.json').write_text(json.dumps(results,indent=2))
print(json.dumps(results,indent=2))
