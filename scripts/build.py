"""공개 GitHub 기록을 조회해 deadhd 상태판 두 개를 site/ 에 만든다.

- 수동 정리 내용은 content/*.base.json 에 있다(정리 기준 SHA 시점의 공개 문서).
- 자동 조회는 main HEAD·최근 병합 PR·열린 PR·main CI 만 다룬다.
  병합이나 CI 성공은 코드 반영·자동 검사 범위의 기록이며, 연구 완료로 표시하지 않는다.
- 조회가 실패하면 직전 배포의 state.json 에서 마지막 성공 결과를 가져와 유지하고,
  실패 사실을 맨 위 줄에 표시한다.
- 로컬 경로·IP·토큰·비공개 링크는 쓰지 않는다. 토큰은 요청 헤더에만 쓴다.
"""
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, 'site')
KST = ZoneInfo('Asia/Seoul')
API = 'https://api.github.com/'
PAGES_URL = os.environ.get('PAGES_URL', '').rstrip('/')
TOKEN = os.environ.get('GITHUB_TOKEN', '')
NOTE = '병합·CI 성공은 코드 반영과 자동 검사 범위의 기록이며 실험·연구 완료를 뜻하지 않는다.'

PROJECTS = [
    {'slug': 'bunkering-ai', 'name': '병커시유',
     'repos': [{'id': 'official', 'repo': 'heechan9/bunkering-ai', 'lane': 1, 'label': '공식'}]},
    {'slug': 'adversarial-ai', 'name': '적대적 AI',
     'repos': [{'id': 'official', 'repo': 'th0oel/AdversarialAI_Security', 'lane': 1, 'label': '공식'},
               {'id': 'fork', 'repo': 'heechan9/AdversarialAI_Security', 'lane': 2, 'label': '개인 포크',
                'upstream': 'th0oel/AdversarialAI_Security'}]},
]


def now_kst():
    return datetime.now(timezone.utc).astimezone(KST)


def fmt(ts):
    """GitHub ISO 시각 → 'YYYY-MM-DD HH:MM KST'."""
    if not ts:
        return '-'
    return datetime.fromisoformat(ts.replace('Z', '+00:00')).astimezone(KST).strftime('%Y-%m-%d %H:%M KST')


def get(path):
    req = urllib.request.Request(API + path, headers={
        'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'deadhd-status'})
    if TOKEN:
        req.add_header('Authorization', 'Bearer ' + TOKEN)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def fetch_repo(spec):
    repo = spec['repo']
    info = get(f'repos/{repo}')
    branch = info['default_branch']
    head = get(f'repos/{repo}/commits/{branch}')
    merged = [p for p in get(f'repos/{repo}/pulls?state=closed&sort=updated&direction=desc&per_page=30')
              if p.get('merged_at')]
    merged.sort(key=lambda p: p['merged_at'], reverse=True)
    open_prs = get(f'repos/{repo}/pulls?state=open&per_page=50')
    runs = get(f'repos/{repo}/actions/runs?head_sha={head["sha"]}&per_page=30').get('workflow_runs', [])
    latest = {}
    for r in runs:  # 워크플로마다 가장 최근 실행 하나
        if r['name'] not in latest or r['created_at'] > latest[r['name']]['created_at']:
            latest[r['name']] = r
    out = {
        'repo': repo, 'branch': branch, 'html': info['html_url'],
        'head': {'sha': head['sha'], 'date': head['commit']['committer']['date'],
                 'title': head['commit']['message'].splitlines()[0][:120], 'url': head['html_url']},
        'merged': [{'n': p['number'], 'title': p['title'][:100], 'at': p['merged_at'], 'url': p['html_url'],
                    'sha': (p.get('merge_commit_sha') or '')[:7]} for p in merged[:6]],
        'open': [{'n': p['number'], 'title': p['title'][:100], 'url': p['html_url'], 'draft': p.get('draft', False), 'headSha': p['head']['sha'], 'baseSha': p['base']['sha']}
                 for p in open_prs],
        'ci': [{'name': r['name'], 'status': r['status'], 'conclusion': r['conclusion'], 'url': r['html_url'],
                'event': r['event'], 'at': r['created_at']} for r in sorted(latest.values(), key=lambda r: r['name'])],
    }
    if spec.get('upstream'):
        owner = repo.split('/')[0]
        name = repo.split('/')[1]
        cmp = get(f'repos/{spec["upstream"]}/compare/{branch}...{owner}:{name}:{branch}')
        out['compare'] = {'status': cmp['status'], 'ahead': cmp['ahead_by'], 'behind': cmp['behind_by'],
                          'url': cmp['html_url']}
    return out


def ci_state(ci):
    if not ci:
        return 'left', '실행 기록 없음'
    if any(r['status'] != 'completed' for r in ci):
        return 'side', '실행 중'
    bad = [r for r in ci if r['conclusion'] not in ('success', 'skipped', 'neutral')]
    if bad:
        return 'blocked', '실패 ' + ', '.join(r['name'] for r in bad)
    return 'done', '성공'


def auto_items(spec, f, project_name):
    """조회 결과 → deadhd 항목. 연구 완료 판정은 하지 않는다."""
    p = spec['id']
    lane = spec['lane']
    fork = spec['id'] == 'fork'
    badge = '자동 조회 · 개인 포크(공식 미반영)' if fork else '자동 조회 · 공식 저장소'
    sha7 = f['head']['sha'][:7]
    items = [{
        'id': f'{p}-head', 'lane': lane, 'label': ('포크 main' if fork else 'main HEAD'), 'sub': sha7,
        'state': 'side' if fork else 'done', 'badge': badge,
        'title': f'{f["repo"]} {f["branch"]} 최신 커밋',
        'body': f'{fmt(f["head"]["date"])} 커밋 {sha7}: {f["head"]["title"]}. ' + NOTE,
        'evidence': [{'icon': 'commit', 'text': f'{f["repo"]}@{sha7}', 'mono': True, 'href': f['head']['url']}]}]
    if fork and 'compare' in f:
        c = f['compare']
        items.append({
            'id': f'{p}-compare', 'lane': lane, 'label': '공식 대비', 'sub': f'+{c["ahead"]} / -{c["behind"]}',
            'state': 'side', 'badge': badge,
            'title': '개인 포크와 공식 저장소의 차이',
            'body': (f'포크 main 은 공식 main 보다 {c["ahead"]} 커밋 앞서고 {c["behind"]} 커밋 뒤에 있다'
                     f'(상태 {c["status"]}). 포크에만 있는 작업은 공식 결과로 표시하지 않는다.'),
            'evidence': [{'icon': 'link', 'text': '공식…포크 비교', 'href': c['url']}]})
    state, word = ci_state(f['ci'])
    items.append({
        'id': f'{p}-ci', 'lane': lane, 'label': 'main CI', 'sub': word, 'state': state, 'badge': badge,
        'title': f'{sha7} 의 GitHub Actions',
        'body': ('main 최신 커밋의 워크플로 결과다. ' + ', '.join(
            f'{r["name"]} {r["conclusion"] or r["status"]}' for r in f['ci']) + '. ' if f['ci']
                 else 'main 최신 커밋에 대한 워크플로 실행 기록이 없다. ') + 'CI 범위 밖의 실험·검증은 이 결과로 판정하지 않는다.',
        'evidence': [{'icon': 'run', 'text': f'{r["name"]} · {r["conclusion"] or r["status"]}', 'href': r['url']}
                     for r in f['ci']]})
    if f['merged']:
        items.append({
            'id': f'{p}-merged', 'lane': lane, 'label': '최근 병합 PR', 'sub': f'#{f["merged"][0]["n"]} 외',
            'state': 'side' if fork else 'done', 'badge': badge,
            'title': '최근 병합된 PR' + (' (포크 내부 병합)' if fork else ''),
            'body': f'가장 최근 병합: #{f["merged"][0]["n"]} ({fmt(f["merged"][0]["at"])}). ' + NOTE,
            'evidence': [{'icon': 'pr', 'text': f'#{m["n"]} {m["title"]} · {fmt(m["at"])}', 'href': m['url']}
                         for m in f['merged']]})
    items.append({
        'id': f'{p}-open', 'lane': lane, 'label': '열린 PR', 'sub': f'{len(f["open"])}개',
        'state': 'side' if f['open'] else 'done', 'badge': badge,
        'title': '열린 PR',
        'body': (f'열린 PR {len(f["open"])}개. 병합 전 작업이며 완료로 표시하지 않는다.' if f['open']
                 else '열린 PR 이 없다.'),
        'evidence': [{'icon': 'pr', 'text': f'#{o["n"]} {o["title"]}' + (' (Draft)' if o['draft'] else ''),
                      'href': o['url']} for o in f['open'][:10]]})
    return items


def load_previous_state():
    if not PAGES_URL:
        return {}
    try:
        with urllib.request.urlopen(PAGES_URL + '/state.json', timeout=30) as r:
            return json.load(r)
    except Exception:
        return {}


def build_project(project, prev, at):
    with open(os.path.join(ROOT, 'content', project['slug'] + '.base.json'), encoding='utf-8') as fh:
        base = json.load(fh)
    curated = base.pop('curatedSha')
    curated_at = base.pop('curatedAt')
    curated_refs = base.pop('curatedRefs', {'official': curated})
    curated_prs = base.pop('curatedPrs', [])
    pstate = {'repos': {}, 'curatedRefs': curated_refs, 'curatedAt': curated_at, 'curatedPrs': curated_prs}
    auto, meta, failures = [], [], []
    for spec in project['repos']:
        key = spec['repo']
        prev_repo = (prev.get(project['slug']) or {}).get('repos', {}).get(key)
        try:
            f = fetch_repo(spec)
            entry = {'ok': True, 'fetchedAt': at.isoformat(timespec='seconds'), 'data': f}
        except Exception as e:  # 네트워크·권한·한도 오류
            reason = type(e).__name__ + (f' {e.code}' if isinstance(e, urllib.error.HTTPError) else '')
            failures.append((spec, reason, prev_repo))
            entry = dict(prev_repo or {}, ok=False, failedAt=at.isoformat(timespec='seconds'), error=reason)
            f = (prev_repo or {}).get('data')
        pstate['repos'][key] = {k: v for k, v in entry.items()}
        if f:
            auto += auto_items(spec, f, project['name'])
            label = f'{spec["label"]} {spec["repo"]} @ {f["head"]["sha"][:7]}'
            meta.append({'text': label, 'href': f['head']['url']})
            last_ok = entry.get('fetchedAt')
            if last_ok:
                meta.append(f'{spec["label"]} 마지막 성공 조회 ' + datetime.fromisoformat(last_ok).astimezone(KST).strftime('%Y-%m-%d %H:%M KST'))
            reference = curated_refs.get(spec['id'])
            if reference:
                meta.append({'text': f'{spec["label"]} 수동 검토 SHA {reference[:7]} ({curated_at})', 'href': f'https://github.com/{key}/commit/{reference}'})
            if reference and f['head']['sha'] != reference:
                auto.append({
                    'id': f'{spec["id"]}-drift', 'lane': spec['lane'], 'label': '정리 이후 변경', 'sub': '검토 필요',
                    'state': 'side', 'badge': '자동 조회',
                    'title': '수동 정리 이후 main 이 바뀌었다',
                    'body': f'아래 수동 정리 항목은 {reference[:7]}({curated_at}) 기준이다. main 은 지금 {f["head"]["sha"][:7]} 이므로 새 기록은 다시 검토해야 반영된다.',
                    'evidence': [{'icon': 'link', 'text': f'{reference[:7]}…{f["head"]["sha"][:7]} 비교',
                                  'href': f'https://github.com/{spec["repo"]}/compare/{reference}...{f["head"]["sha"]}'}]})
    for review in curated_prs:
        entry = pstate['repos'].get(review['repo'], {})
        current = next((p for p in entry.get('data', {}).get('open', []) if p['n'] == review['number']), None)
        meta.append({'text': '수동 검토 PR' + f" #{review['number']} @ {review['sha'][:7]}", 'href': f"https://github.com/{review['repo']}/commit/{review['sha']}"})
        if entry.get('ok') and (not current or current.get('headSha') != review['sha']):
            lane = next(s['lane'] for s in project['repos'] if s['repo'] == review['repo'])
            auto.append({'id': f"pr-drift-{review['repo'].split('/')[0]}-{review['number']}", 'lane': lane, 'label': 'PR 정리 이후 변경', 'sub': '검토 필요', 'state': 'side', 'title': f"PR #{review['number']} 수동 기록 재검토 필요", 'body': '검토한 head와 달라졌거나 열린 PR 목록에서 사라졌다. 병합·완료로 자동 승격하지 않는다.', 'evidence': [{'text': 'PR 상태 확인', 'href': f"https://github.com/{review['repo']}/pull/{review['number']}"}]})
    for spec, reason, prev_repo in failures:
        when = (prev_repo or {}).get('fetchedAt')
        kept = ('직전 성공 조회(' + datetime.fromisoformat(when).astimezone(KST).strftime('%Y-%m-%d %H:%M KST') + ') 내용을 유지한다.') if when else '유지할 이전 조회 결과가 없다.'
        auto.insert(0, {'id': f'{spec["id"]}-fail', 'lane': spec['lane'], 'label': '갱신 실패', 'sub': reason,
                        'state': 'blocked', 'badge': '자동 조회 실패',
                        'title': f'{spec["repo"]} 조회 실패',
                        'body': f'{at.strftime("%Y-%m-%d %H:%M KST")} 조회가 실패했다({reason}). {kept}'})
    data = base
    data['updated'] = at.strftime('%Y-%m-%d %H:%M KST')
    data['meta'] = ([f'자동 조회 시각 {data["updated"]}' + (' · 일부 실패' if failures else ''), f'수동 내용 검토 시각 {curated_at}'] + meta)
    lanes_used = {}
    items = auto + data['items']
    for i in items:  # 같은 줄 안에서 차례대로 칸을 매긴다
        i['col'] = lanes_used.get(i['lane'], 0)
        lanes_used[i['lane']] = i['col'] + 1
    data['items'] = items
    pstate['curatedSha'] = curated
    return data, pstate


def render(data, out):
    vendor = os.path.join(ROOT, 'vendor', 'deadhd')
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, 'data.json')
        with open(src, 'w', encoding='utf-8') as fh:
            json.dump(data, fh, ensure_ascii=False)
        env = {k: v for k, v in os.environ.items() if k not in ('CLAUDE_CODE_SESSION_ID', 'GITHUB_TOKEN')}
        env.update(XDG_CONFIG_HOME=os.path.join(tmp, 'cfg'), DEADHD_HISTORY=os.path.join(tmp, 'history.jsonl'),
                   DEADHD_STATE_DIR=os.path.join(tmp, 'state'), DEADHD_NOW=now_kst().isoformat(timespec='seconds'))
        subprocess.run([sys.executable, os.path.join(vendor, 'render.py'), '--theme', 'dark', '--font', 'pretendard',
                        src, out], check=True, env=env, cwd=tmp)
    # Code, experiments, extensions and submission steps have different weights.
    # Keep the upstream design, but do not present their card ratio as research progress.
    with open(out, encoding='utf-8') as fh:
        html = fh.read()
    html = html.replace('</head>', '''<style id="research-scope-style">
.progress .bar,.cx-bar,.cc-ring svg,.cc-seg,#countLabel{display:none!important}
.progress{grid-template-columns:1fr}.count-col{justify-self:end}
.research-scope-note{max-width:1100px;margin:16px auto;padding:12px 18px;color:#9aa3b2;font:14px/1.6 system-ui,sans-serif}
</style></head>''')
    html = html.replace("$('countB').textContent = doneList.length + '/' + total;",
                        "$('countB').textContent = '완료 항목 ' + doneList.length + '/' + total;")
    html = html.replace('<b>${doneList.length}/${total}</b>', '<b>완료 항목 ${doneList.length}/${total}</b>')
    html = html.replace('</b>${L.countDone}${data.eta', '</b>${data.eta')
    html = html.replace('<div id="compact" hidden></div>', '''<aside class="research-scope-note">표시된 작업 항목 기준이며 연구 완성률은 아닙니다. 본 연구·재현과 후속 확장·최종 제출 절차를 구분해 읽어 주세요. 자동 Git·CI 결과는 해당 코드 검사의 상태이며 실험·제출 완료를 뜻하지 않습니다.</aside>
<div id="compact" hidden></div>''')
    with open(out, 'w', encoding='utf-8') as fh:
        fh.write(html)


INDEX = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>프로젝트 상태판</title>
<style>
:root{{color-scheme:dark}}body{{margin:0;background:#0f1115;color:#e7e9ee;font:16px/1.6 system-ui,sans-serif;padding:24px 16px}}
main{{max-width:560px;margin:0 auto}}a.card{{display:block;padding:18px 20px;margin:12px 0;border:1px solid #2a2f3a;border-radius:12px;
color:inherit;text-decoration:none;background:#161a22}}a.card b{{font-size:20px}}small{{color:#9aa3b2}}footer{{margin-top:28px;color:#9aa3b2;font-size:13px}}
footer a{{color:#9ab}}</style></head><body><main>
<h1 style="font-size:22px">프로젝트 상태판</h1>
<p><small>마지막 조회 {at}{fail}. 공개 GitHub 기록만 사용하며 1시간마다 갱신한다.</small></p>
<a class="card" href="bunkering-ai.html"><b>병커시유</b><br><small>heechan9/bunkering-ai</small></a>
<a class="card" href="adversarial-ai.html"><b>적대적 AI</b><br><small>th0oel/AdversarialAI_Security · 개인 포크 heechan9/AdversarialAI_Security</small></a>
<footer>페이지 디자인: <a href="https://github.com/lcalmsky/deadhd">deadhd</a> v1.9.0 (MIT License, © 2026 lcalmsky).
병합·CI 성공은 연구 완료를 뜻하지 않는다.</footer>
</main></body></html>
"""


def main():
    os.makedirs(SITE, exist_ok=True)
    at = now_kst()
    prev = load_previous_state()
    state = {'generatedAt': at.isoformat(timespec='seconds')}
    any_fail = False
    for project in PROJECTS:
        data, pstate = build_project(project, prev, at)
        any_fail = any_fail or any(not r.get('ok') for r in pstate['repos'].values())
        state[project['slug']] = pstate
        render(data, os.path.join(SITE, project['slug'] + '.html'))
    with open(os.path.join(SITE, 'state.json'), 'w', encoding='utf-8') as fh:
        json.dump(state, fh, ensure_ascii=False, indent=1)
    with open(os.path.join(SITE, 'index.html'), 'w', encoding='utf-8') as fh:
        fh.write(INDEX.format(at=at.strftime('%Y-%m-%d %H:%M KST'), fail=' · 일부 조회 실패' if any_fail else ''))
    open(os.path.join(SITE, '.nojekyll'), 'w').close()
    print('built', at.isoformat(timespec='seconds'), 'failures' if any_fail else 'ok')


if __name__ == '__main__':
    main()
