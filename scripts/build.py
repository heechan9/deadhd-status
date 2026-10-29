"""공개 GitHub 기록을 조회해 deadhd 상태판을 site/ 에 만든다.

- 수동 정리 내용은 content/*.base.json 에 있다(정리 기준 SHA 시점의 공개 문서).
- 자동 조회는 main HEAD·최근 병합 PR·열린 PR·main CI 와, 카드에 연결된 PR 의
  Draft·병합 여부·head CI 결과를 다룬다.
- 카드 완료는 content/<slug>.completion.json 의 규칙(scripts/completion.py)으로만 바뀐다.
  자동 완료는 '코드 반영(main 병합)'을 명시한 카드·하위 작업에 한정되고, countScope 는 바꾸지 않는다.
  병합이나 CI 성공은 연구 성과·팀원 본인 확인·계약 채택·최종 제출의 완료로 표시하지 않는다.
- 조회가 실패하면 직전 배포의 state.json 에서 마지막 성공 결과를 가져와 유지하고,
  실패 사실을 맨 위 줄에 표시한다.
- 로컬 경로·IP·토큰·비공개 링크는 쓰지 않는다. 토큰은 요청 헤더에만 쓴다.
"""
import json
from html import escape
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import completion  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, 'site')
KST = ZoneInfo('Asia/Seoul')
API = 'https://api.github.com/'
PAGES_URL = os.environ.get('PAGES_URL', '').rstrip('/')
TOKEN = os.environ.get('GITHUB_TOKEN', '')
NOTE = '병합·CI 성공은 코드 반영과 자동 검사 범위의 기록이며 실험·연구 완료를 뜻하지 않는다.'
LIVE_NOTE = '이 줄은 PR 상태와 해당 head 의 자동 검사 기록일 뿐 연구 성과·팀원 본인 확인·계약 채택·최종 제출의 완료를 뜻하지 않는다. 카드 상태는 명시된 완료 규칙을 따르며 코드 반영(main 병합) 대상만 자동 완료될 수 있다.'
AUTO_STALE_HOURS = 3      # 매시간 조회하므로 3시간 넘게 갱신되지 못한 자동 기록은 '오래됨'
CURATED_STALE_DAYS = 3    # 수동 내용 검토가 이보다 오래되면 '오래됨'
MAX_LINKED_PRS = 60       # 한 프로젝트에서 조회할 연결 PR 상한(API 한도 보호)
PR_URL_RE = re.compile(r'^https://github\.com/([^/\s]+/[^/\s]+)/pull/(\d+)/?$')

PROJECTS = [
    {'slug': 'bunkering-ai', 'name': '병커시유',
     'repos': [{'id': 'official', 'repo': 'heechan9/bunkering-ai', 'lane': 1, 'label': '공식'}]},
    {'slug': 'adversarial-ai', 'name': '적대적 AI',
     'repos': [{'id': 'official', 'repo': 'th0oel/AdversarialAI_Security', 'lane': 1, 'label': '공식'},
               {'id': 'fork', 'repo': 'heechan9/AdversarialAI_Security', 'lane': 2, 'label': '개인 포크',
                'upstream': 'th0oel/AdversarialAI_Security'}]},
    {'slug': 'fabguard-ai', 'name': 'FabGuard AI',
     'repos': [{'id': 'official', 'repo': 'heechan9/fabguard-ai', 'lane': 1, 'label': '공식'}]},
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
    if any(r['conclusion'] != 'success' for r in ci):
        return 'side', '성공 미확인(skipped/neutral 포함)'
    return 'done', '성공'


def err_reason(e):
    return type(e).__name__ + (f' {e.code}' if isinstance(e, urllib.error.HTTPError) else '')


def parse_kst(text):
    """'YYYY-MM-DD HH:MM KST' 또는 시차 있는 ISO 시각 → aware datetime. 해석할 수 없으면 None."""
    if not isinstance(text, str):
        return None
    t = text.strip()
    try:
        if t.endswith(' KST'):
            return datetime.strptime(t[:-4], '%Y-%m-%d %H:%M').replace(tzinfo=KST)
        dt = datetime.fromisoformat(t.replace('Z', '+00:00'))
    except ValueError:
        return None
    return dt if dt.tzinfo else None


def age_text(delta):
    hours = int(delta.total_seconds() // 3600)
    return f'{hours // 24}일 전' if hours >= 48 else f'{max(hours, 0)}시간 전'


def is_stale(iso, at, hours=AUTO_STALE_HOURS):
    when = parse_kst(iso)
    return when is None or at - when > timedelta(hours=hours)


# ---- 카드에 연결된 PR 의 실제 상태 ---------------------------------------------------------
def pr_key(repo, number):
    return f'{repo}#{number}'


def linked_prs(item):
    """카드에 연결된 PR [(repo, number)]. linkedPrs 가 있으면 그것만, 없으면 evidence 의 PR 링크.

    liveStatus: false 이면 이 카드는 자동 갱신하지 않는다."""
    if item.get('liveStatus') is False:
        return []
    found = []
    if item.get('linkedPrs') is not None:
        for e in item['linkedPrs']:
            if isinstance(e, str):
                m = re.fullmatch(r'([^/\s#]+/[^/\s#]+)#(\d+)', e.strip())
                pair = (m.group(1), int(m.group(2))) if m else None
            elif isinstance(e, dict) and isinstance(e.get('repo'), str) and isinstance(e.get('number'), int):
                pair = (e['repo'], e['number'])
            else:
                pair = None
            if pair is None:
                raise ValueError(f'{item.get("id")}: linkedPrs 형식 오류 {e!r} ("owner/repo#N" 또는 {{repo, number}})')
            found.append(pair)
    else:
        for ev in item.get('evidence') or []:
            m = PR_URL_RE.match(ev.get('href') or '') if isinstance(ev, dict) else None
            if m:
                found.append((m.group(1), int(m.group(2))))
    return list(dict.fromkeys(found))


def fetch_pr(repo, number):
    """PR 하나의 Draft·병합 여부와 현재 head 의 워크플로 결과."""
    p = get(f'repos/{repo}/pulls/{number}')
    head = p['head']['sha']
    runs = get(f'repos/{repo}/actions/runs?head_sha={head}&per_page=50').get('workflow_runs', [])
    latest = {}
    for r in runs:  # 워크플로마다 가장 최근 실행 하나
        if r['name'] not in latest or r['created_at'] > latest[r['name']]['created_at']:
            latest[r['name']] = r
    merged = bool(p.get('merged_at'))
    return {
        'repo': repo, 'n': number, 'title': p['title'][:100], 'url': p['html_url'],
        'state': p['state'], 'draft': bool(p.get('draft')), 'merged': merged, 'mergedAt': p.get('merged_at'),
        'mergeSha': (p.get('merge_commit_sha') or '')[:7] if merged else '',
        'headSha': head, 'baseRef': p['base']['ref'], 'updatedAt': p.get('updated_at'),
        'ci': [{'name': r['name'], 'status': r['status'], 'conclusion': r['conclusion'], 'url': r['html_url'],
                'event': r['event'], 'at': r['created_at']} for r in sorted(latest.values(), key=lambda r: r['name'])],
    }


def refresh_prs(pairs, prev_prs, at):
    """연결 PR 을 조회한다. 실패하면 직전 성공 기록을 유지하되 ok=False 로 표시한다."""
    out = {}
    stamp = at.isoformat(timespec='seconds')
    for i, (repo, number) in enumerate(pairs):
        key = pr_key(repo, number)
        prev = (prev_prs or {}).get(key) or {}
        if i >= MAX_LINKED_PRS:
            out[key] = dict(prev, ok=False, failedAt=stamp, error='조회 상한 초과')
            continue
        try:
            out[key] = {'ok': True, 'fetchedAt': stamp, 'data': fetch_pr(repo, number)}
        except Exception as e:  # 네트워크·권한·한도·응답 형식 오류
            out[key] = dict(prev, ok=False, failedAt=stamp, error=err_reason(e))
    return out


def pr_state_word(r):
    if r['merged']:
        return '병합됨 ' + fmt(r['mergedAt'])
    if r['state'] == 'closed':
        return '닫힘(미병합)'
    return '열림·Draft' if r['draft'] else '열림(Draft 아님)'


def pr_ci_word(r):
    _, word = ci_state(r['ci'])
    if r['ci'] and word in ('성공', '실행 중'):
        word += '(' + ', '.join(c['name'] for c in r['ci']) + ')'
    return word


def pr_short(entry, at):
    """증거 링크 뒤에 붙이는 짧은 자동 상태."""
    d = entry.get('data')
    if not d:
        return '조회 실패·이전 기록 없음'
    text = pr_state_word(d) + ' · CI ' + pr_ci_word(d)
    if not entry.get('ok'):
        when = parse_kst(entry.get('fetchedAt'))
        text += ' · 조회 실패, ' + (age_text(at - when) + ' 기록' if when else '기록 시각 불명')
    return text


def pr_line(repo, number, entry, at, default_repo, curated_head=None):
    ref = f'#{number}' if repo == default_repo else f'{repo}#{number}'
    d = (entry or {}).get('data')
    if not d:
        reason = (entry or {}).get('error', '기록 없음')
        return f'{ref} 조회 실패({reason}) · 이전 성공 기록 없음'
    line = f'{ref} {pr_state_word(d)} · head {d["headSha"][:7]} · CI {pr_ci_word(d)}'
    if curated_head and curated_head != d['headSha']:
        line += f' · 수동 검토 head {curated_head[:7]} 이후 변경'
    if not entry.get('ok'):
        when = parse_kst(entry.get('fetchedAt'))
        line += f' · 조회 실패({entry.get("error")}), 마지막 성공 ' + (
            f'{fmt(entry["fetchedAt"])} 기록({age_text(at - when)}' + (' · 오래됨)' if is_stale(entry['fetchedAt'], at) else ')')
            if when else '시각 불명')
    return line


def overlay_live(items, prs, at, default_repo, curated_heads):
    """수동 카드에 연결 PR 의 실제 상태를 덧붙인다. state·countScope·badge 등은 건드리지 않는다.

    반환값은 덧붙인 카드 수. linkedPrs·liveStatus 같은 내부 키는 렌더 전에 지운다."""
    touched = 0
    stamp = at.strftime('%m-%d %H:%M KST')
    for item in items:
        pairs = linked_prs(item)
        item.pop('linkedPrs', None)
        item.pop('liveStatus', None)
        if not pairs:
            continue
        lines = []
        for repo, number in pairs:
            entry = prs.get(pr_key(repo, number))
            lines.append(pr_line(repo, number, entry, at, default_repo, curated_heads.get((repo, number))))
            for ev in item.get('evidence') or []:
                m = PR_URL_RE.match(ev.get('href') or '') if isinstance(ev, dict) else None
                if m and (m.group(1), int(m.group(2))) == (repo, number) and entry:
                    ev['text'] = f'{ev["text"]} ｜자동: {pr_short(entry, at)}'
        item['body'] = (item.get('body') or '').rstrip() + f' [자동 조회 {stamp}] ' + ' / '.join(lines) + '. ' + LIVE_NOTE
        touched += 1
    return touched


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
            reason = err_reason(e)
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
                meta.append(f'{spec["label"]} 마지막 성공 조회 ' + datetime.fromisoformat(last_ok).astimezone(KST).strftime('%Y-%m-%d %H:%M KST')
                            + ('' if entry.get('ok') else f' ({age_text(at - parse_kst(last_ok))}' + (' · 오래됨)' if is_stale(last_ok, at) else ')')))
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
    default_repo = project['repos'][0]['repo']
    first_lane = project['repos'][0]['lane']
    curated_heads = {(r['repo'], r['number']): r['sha'] for r in curated_prs}
    spec = completion.load_spec(ROOT, project['slug'])
    if spec:
        completion.validate_spec(spec, base['items'])  # 구성 오류는 조용히 넘기지 않고 빌드를 멈춘다
    pairs = []
    for card in base['items']:
        pairs += linked_prs(card)
    pairs += list(curated_heads)
    if spec:
        pairs += completion.rule_prs(spec)
    pairs = list(dict.fromkeys(pairs))
    prs = refresh_prs(pairs, (prev.get(project['slug']) or {}).get('prs', {}), at)
    pstate['prs'] = prs
    if spec:
        results = completion.apply(spec, base['items'], prs, at, parse_kst, CURATED_STALE_DAYS)
        pstate['completion'] = {cid: {k: r[k] for k in ('status', 'done', 'total', 'state', 'target')}
                                for cid, r in results.items()}
    overlay_live(base['items'], prs, at, default_repo, curated_heads)
    pr_failed = [k for k, e in prs.items() if not e.get('ok')]
    if pr_failed:
        shown = pr_failed[:10]
        auto.insert(0, {
            'id': 'pr-live-failed', 'lane': first_lane, 'label': 'PR 상태 갱신 실패', 'sub': f'{len(pr_failed)}건',
            'state': 'blocked', 'badge': '자동 조회 실패',
            'title': '카드에 연결된 PR 조회 실패',
            'body': (f'{at.strftime("%Y-%m-%d %H:%M KST")} 연결 PR {len(pairs)}건 중 {len(pr_failed)}건을 조회하지 못했다. '
                     '해당 카드에는 마지막 성공 기록과 경과 시간을 표시하거나, 기록이 없음을 표시한다. 조회 실패를 PR 상태나 CI 결과로 해석하지 않는다.'),
            'evidence': [{'text': k, 'href': f'https://github.com/{k.split("#")[0]}/pull/{k.split("#")[1]}'} for k in shown]})
    curated_dt = parse_kst(curated_at)
    curated_stale = curated_dt is None or at - curated_dt > timedelta(days=CURATED_STALE_DAYS)
    if curated_stale:
        auto.append({
            'id': 'curated-stale', 'lane': first_lane, 'label': '수동 검토 오래됨',
            'sub': '시각 해석 불가' if curated_dt is None else age_text(at - curated_dt),
            'state': 'side', 'badge': '자동 조회',
            'title': '수동 내용 검토 시각이 오래됐다',
            'body': (f'수동 내용 검토 시각 {curated_at}'
                     + (' 을(를) 해석할 수 없다.' if curated_dt is None else f' 이후 {CURATED_STALE_DAYS}일이 넘었다.')
                     + ' 아래 수동 정리 항목은 다시 검토해야 최신 근거로 볼 수 있다. 자동 조회 결과로 수동 항목을 갱신하거나 완료 처리하지 않는다.')})
    for review in curated_prs:
        entry = pstate['repos'].get(review['repo'], {})
        current = next((p for p in entry.get('data', {}).get('open', []) if p['n'] == review['number']), None)
        meta.append({'text': '수동 검토 PR' + f" #{review['number']} @ {review['sha'][:7]}", 'href': f"https://github.com/{review['repo']}/commit/{review['sha']}"})
        if entry.get('ok') and (not current or current.get('headSha') != review['sha']):
            lane = next(s['lane'] for s in project['repos'] if s['repo'] == review['repo'])
            auto.append({'id': f"pr-drift-{review['repo'].split('/')[0]}-{review['number']}", 'lane': lane, 'label': 'PR 정리 이후 변경', 'sub': '검토 필요', 'state': 'side', 'title': f"PR #{review['number']} 수동 기록 재검토 필요", 'body': '검토한 head와 달라졌거나 열린 PR 목록에서 사라졌다.' + (' 현재 자동 조회: ' + pr_line(review['repo'], review['number'], prs.get(pr_key(review['repo'], review['number'])), at, default_repo) + '.' if prs.get(pr_key(review['repo'], review['number'])) else '') + ' 병합·완료로 자동 승격하지 않는다.', 'evidence': [{'text': 'PR 상태 확인', 'href': f"https://github.com/{review['repo']}/pull/{review['number']}"}]})
    for spec, reason, prev_repo in failures:
        when = (prev_repo or {}).get('fetchedAt')
        kept = ('직전 성공 조회(' + datetime.fromisoformat(when).astimezone(KST).strftime('%Y-%m-%d %H:%M KST')
                + ', ' + age_text(at - parse_kst(when)) + (' · 오래됨' if is_stale(when, at) else '') + ') 내용을 유지한다.') if when else '유지할 이전 조회 결과가 없다.'
        auto.insert(0, {'id': f'{spec["id"]}-fail', 'lane': spec['lane'], 'label': '갱신 실패', 'sub': reason,
                        'state': 'blocked', 'badge': '자동 조회 실패',
                        'title': f'{spec["repo"]} 조회 실패',
                        'body': f'{at.strftime("%Y-%m-%d %H:%M KST")} 조회가 실패했다({reason}). {kept}'})
    data = base
    data['updated'] = at.strftime('%Y-%m-%d %H:%M KST')
    pr_ok = len(prs) - len(pr_failed)
    data['meta'] = ([f'자동 조회 시각 {data["updated"]}' + (' · 일부 실패' if failures or pr_failed else ''),
                     f'수동 내용 검토 시각 {curated_at}' + (' · 오래됨' if curated_stale else '')]
                    + ([f'카드 연결 PR 조회 {pr_ok}/{len(prs)}' + (' · 일부 실패' if pr_failed else '')] if prs else []) + meta)
    lanes_used = {}
    items = auto + data['items']
    for i in items:  # 같은 줄 안에서 차례대로 칸을 매긴다
        i['col'] = lanes_used.get(i['lane'], 0)
        lanes_used[i['lane']] = i['col'] + 1
    data['items'] = items
    pstate['curatedSha'] = curated
    return data, pstate


COMPLETION_JS = r"""
  (function () {
    const escC = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
    const box = document.getElementById('completionSummary');
    const judged = items.filter(i => i.completion);
    if (!box || !judged.length) return;
    const sub = judged.filter(i => i.completion.total > 0);
    const req = sub.filter(i => i.countScope === 'submission' && i.completion.status !== 'complete');
    const other = sub.filter(i => i.countScope !== 'submission' && i.completion.status === 'partial');
    const unverified = judged.reduce((n, i) => n + (i.completion.unverified || 0), 0);
    const conflicts = judged.filter(i => i.completion.conflict).length;
    const line = i => '<li>' + escC(i.label) + ' <b>' + i.completion.done + '/' + i.completion.total + '</b> 하위 조건 완료'
      + (i.completion.milestonesTotal ? ' · 참고 진행 ' + i.completion.milestonesDone + '/' + i.completion.milestonesTotal + ' (부모 완료 조건 아님)' : '')
      + (i.completion.remaining.length ? ' · 남은: ' + i.completion.remaining.slice(0, 4).map(escC).join(' / ') + (i.completion.remaining.length > 4 ? ' 외 ' + (i.completion.remaining.length - 4) + '건' : '') : '') + '</li>';
    let h = '<b>완료 판정</b> 필수 ' + requiredDone + '/' + requiredTotal + ' 완료. 하위 조건 일부만 끝난 항목은 완료 수에 넣지 않고 아래에 따로 보인다.';
    if (req.length) h += '<ul>' + req.map(line).join('') + '</ul>';
    if (other.length) h += '<div>필수 집계 밖 부분 진행</div><ul>' + other.map(line).join('') + '</ul>';
    if (unverified) h += '<div class="warn">자동 확인 불가·오래된 기록 하위 조건 ' + unverified + '건: 새 완료로 세지 않았다.</div>';
    if (conflicts) h += '<div class="warn">수동 정리와 자동 조회가 어긋난 카드 ' + conflicts + '건: 자동으로 되돌리지 않고 재검토를 요청한다.</div>';
    h += '<div>코드 반영(main 병합)만 자동으로 완료가 된다. 연구 성과·담당자 본인 확인·계약 채택·최종 제출은 CI 성공이나 병합으로 완료가 되지 않는다.</div>';
    box.innerHTML = h;
    box.hidden = false;
  })();
"""



def project_summary_html(summary):
    """Evidence categories are independent; never sum into a completion ratio."""
    parts = ['<section id="projectSummary" class="research-scope-note project-summary" aria-label="확인 범위별 현황">',
             '<h2>' + escape(summary['title']) + '</h2>',
             '<p>' + escape(summary['note']) + '</p>',
             '<p class="summary-checked">근거 검토 시각 ' + escape(summary['checkedAt']) + '</p>',
             '<div class="summary-groups">']
    for group in summary['groups']:
        members = group['items']
        done = sum(item['state'] == 'done' for item in members)
        if any(item['state'] not in ('done', 'unverified') for item in members):
            raise ValueError('invalid project summary state')
        parts += ['<article class="summary-group" data-group="' + escape(group['id'], quote=True) + '">',
                  '<h3>' + escape(group['label']) + ' <b>' + str(done) + '/' + str(len(members)) + '</b></h3>', '<ul>']
        for item in members:
            state = '확인됨' if item['state'] == 'done' else '미확인'
            parts += ['<li><strong>' + escape(item['label']) + '</strong> · ' + state,
                      '<p>' + escape(item['detail']) + '</p>']
            for evidence in item['evidence']:
                label = escape(evidence['label'])
                href = evidence.get('href', '')
                if href.startswith(('https://', 'http://')):
                    parts.append('<a target="_blank" rel="noopener" href="' + escape(href, quote=True) + '">' + label + '</a> ')
                else:
                    parts.append('<span>' + label + '</span> ')
            parts.append('</li>')
        parts.append('</ul></article>')
    parts.append('</div><h3>별도 확인할 사항</h3><ul>')
    for item in summary.get('remaining', []):
        parts.append('<li><strong>' + escape(item['label']) + '</strong> · ' + escape(item['detail']) + '</li>')
    parts.append('</ul></section>')
    return ''.join(parts)


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
.research-scope-note{max-width:1100px;margin:16px auto;padding:12px 18px;color:#9aa3b2;font:14px/1.6 system-ui,sans-serif}
.completion-summary b{color:#e7e9ee}.completion-summary ul{margin:6px 0 0;padding-left:20px}.completion-summary .warn{color:#e5b567}
.fnode.partial .node{border-style:dashed;border-width:3px;border-color:var(--now);color:var(--now)}
.fnode.partial .sub{color:var(--now);font-weight:500}
.cc-seg span.partial{box-shadow:inset 0 -3px 0 var(--now)}
</style></head>''')
    html = html.replace('const total = items.length;', '''const total = items.length;
  const requiredItems = items.filter(i => i.countScope === 'submission');
  const requiredDone = requiredItems.filter(i => i.state === 'done').length;
  const requiredTotal = requiredItems.length;''')
    html = html.replace('const byState = st => items.filter(i => i.state === st);',
                        "const byState = st => items.filter(i => i.state === st && i.countScope === 'submission');")
    html = html.replace("$('countB').textContent = doneList.length + '/' + total;",
                        "$('countB').textContent = requiredDone + '/' + requiredTotal;\n" + COMPLETION_JS)
    # 부분 완료(하위 조건 일부만 충족)는 노드·점에 따로 표시한다. state 와 필수 집계는 바꾸지 않는다.
    html = html.replace("const node = el('div', 'fnode ' + it.state);",
                        "const node = el('div', 'fnode ' + it.state + (it.completion && it.completion.status === 'partial' ? ' partial' : ''));")
    html = html.replace("countDone: '완료'", "countDone: '제출 필수 완료'")
    html = html.replace('<b>${doneList.length}/${total}</b>', '<b>${requiredDone}/${requiredTotal}</b>')
    html = html.replace('const pct = total ? (doneList.length / total * 100) : 0;',
                        'const pct = requiredTotal ? (requiredDone / requiredTotal * 100) : 0;')
    html = html.replace('const C = 2 * Math.PI * 15, f = total ? doneList.length / total * C : 0;',
                        'const C = 2 * Math.PI * 15, f = requiredTotal ? requiredDone / requiredTotal * C : 0;')
    html = html.replace('${items.map(i => `<span class="${i.state}" title="${esc(i.label)}"></span>`)',
                        '${requiredItems.map(i => `<span class="${i.state}${i.completion && i.completion.status === \'partial\' ? \' partial\' : \'\'}" title="${esc(i.label)}"></span>`)')
    html = html.replace('blockedList.forEach(it => blockedWrap', "blockedList.filter(i => i.countScope === 'submission').forEach(it => blockedWrap")
    html = html.replace("L.secDone, doneList, () => 'done'", "L.secDone, doneList.filter(i => i.countScope === 'submission'), () => 'done'")
    html = html.replace('const rest = sideList.concat(leftList);', "const rest = sideList.concat(leftList).filter(i => i.countScope === 'submission');")
    html = html.replace('const vNow = nowList[0] || blockedList[0] || null;', "const vNow = requiredItems.find(i => i.state === 'now') || requiredItems.find(i => i.state === 'blocked') || null;")
    html = html.replace('const order = [...doneList, ...(vNow ? [vNow] : []), ...leftList, ...sideList];', "const order = [...doneList, ...(vNow ? [vNow] : []), ...leftList, ...sideList].filter(i => i.countScope === 'submission');")
    for state, variable in [('done', 'doneList'), ('blocked', 'blockedList'), ('left', 'leftList'), ('side', 'sideList')]:
        html = html.replace(f"['{state}', L.tally.{state}, {variable}]", f"['{state}', L.tally.{state}, requiredItems.filter(i => i.state === '{state}')]")
    html = html.replace('  if (Array.isArray(data.changes)', '''  const referenceItems = items.filter(i => i.countScope !== 'submission' && i.countScope !== 'after-submission');
  if (referenceItems.length) section('left', 'ℹ', '참고 정보 · 자동 Git/CI·검증 이력 (필수 집계 제외)', referenceItems, i => i.state);
  const afterSubmission = items.filter(i => i.countScope === 'after-submission');
  if (afterSubmission.length) section('left', '○', '제출 이후 · 확장·후속 작업 (필수 집계 제외)', afterSubmission, i => i.state);
  if (Array.isArray(data.changes)''')
    html = html.replace('<div class="tally" id="tally"></div>', '<div id="completionSummary" class="research-scope-note completion-summary" hidden></div><p class="research-scope-note">아래 상태별 집계도 이번 제출 필수 항목 기준입니다.</p><div class="tally" id="tally"></div>')
    html = html.replace('<div id="compact" hidden></div>', '''<aside class="research-scope-note">이번 최종제출 필수 항목만 집계하며 연구 완성률은 아닙니다. 완료한 본 연구와 현재 주장에 영향을 주는 미해결 검증은 포함합니다. 제출 이후 연구·새 기능과 자동 Git·CI 참고 정보는 집계에서 제외합니다.</aside>
<div id="compact" hidden></div>''')
    if data.get('currentProjectSummary'):
        # Keep the immutable legacy cards, but do not portray their old tally as
        # today's project completion ratio, in any original/compact view.
        html = html.replace(COMPLETION_JS, '')
        html = html.replace("$('countB').textContent = requiredDone + '/' + requiredTotal;", "$('countB').textContent = '';" )
        html = html.replace('<b>${requiredDone}/${requiredTotal}</b>', '')
        html = html.replace('</head>', '<style id="project-summary-style">.progress,#tally,#completionSummary,.cx-count,.cx-bar,.cc-ring,.cc-seg{display:none!important}.summary-groups{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,250px),1fr));gap:16px}.summary-group{border:1px solid var(--card-line);border-radius:14px;padding:16px;background:var(--card);min-width:0;overflow-wrap:anywhere}.summary-group h3{margin:0}.summary-group ul{padding-left:18px}.summary-group li{margin:14px 0}.summary-group p{margin:5px 0}.summary-group a{color:var(--done-2)}.project-summary h2{margin-top:12px}.summary-checked{font-size:12px}</style></head>')
        html = html.replace('<div id="compact" hidden></div>', project_summary_html(data['currentProjectSummary']) + '<div id="compact" hidden></div>')
        html = html.replace('이번 최종제출 필수 항목만 집계하며 연구 완성률은 아닙니다. 완료한 본 연구와 현재 주장에 영향을 주는 미해결 검증은 포함합니다. 제출 이후 연구·새 기능과 자동 Git·CI 참고 정보는 집계에서 제외합니다.', '현재 프로젝트는 아래 세 가지 확인 범위를 따로 표시합니다. 합산 완료율은 사용하지 않습니다. 아래 기존 그래프·카드는 근거와 과거 판정을 보존한 이력이며 최신 전체 진행률이 아닙니다.')
        html = html.replace('아래 상태별 집계도 이번 제출 필수 항목 기준입니다.', '아래는 기존 카드의 근거·판정 이력입니다. 지난 ACK 일정과 과거 팀 자료 취합을 현재 프로젝트 완료율에 합산하지 않습니다.')
        html = html.replace("countDone: '제출 필수 완료'", "countDone: '과거 카드 판정'")
    if data.get('evidenceOnly'):
        # No submission contract exists for this evidence page. Do not display a
        # fictitious 0/0 completion rate or empty submission-only compact views.
        html = html.replace('</head>', '<style id="evidence-only-style">.progress,#tally,#completionSummary,.viewbar .seg-ctl,#compact{display:none!important}body[data-view] main{display:block!important}</style></head>')
        html = html.replace('이번 최종제출 필수 항목만 집계하며 연구 완성률은 아닙니다. 완료한 본 연구와 현재 주장에 영향을 주는 미해결 검증은 포함합니다. 제출 이후 연구·새 기능과 자동 Git·CI 참고 정보는 집계에서 제외합니다.', '근거별 상태판입니다. 제출 완료율·연구 완성률은 집계하지 않습니다. 합성 3D 시연, 미병합 Draft, 실제 현장 검증을 구분합니다.')
        html = html.replace('아래 상태별 집계도 이번 제출 필수 항목 기준입니다.', '자동 Git/CI 조회와 수동 내용 검토 시각을 구분합니다.')
        html = html.replace('참고 정보 · 자동 Git/CI·검증 이력 (필수 집계 제외)', '구현·Draft·검증 근거와 남은 한계')
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
<a class="card" href="fabguard-ai.html"><b>FabGuard AI</b><br><small>합성 3D 시연 · 센서 기록 Draft · 검증 한계</small></a>
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
        any_fail = any_fail or any(not r.get('ok') for r in pstate['repos'].values()) \
            or any(not r.get('ok') for r in pstate.get('prs', {}).values())
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

