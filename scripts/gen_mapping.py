"""docs/completion-mapping.md 를 content/bunkering-ai.{base,completion}.json 에서 만든다(네트워크 없음).

각 카드의 전/후 state·countScope·완료 대상·승인 기준·판정·근거 URL·확인 시각·남은 조건을 표로 남긴다.
'후' 는 두 가지 가정으로 계산한다.
- A: 이번 환경처럼 GitHub 조회가 모두 실패(실측 HTTP 403)한 빌드 — 수동 정리 기준만 남고 새 완료는 없다.
- B: 직전 Codex 공개 조회 보고(2026-10-27)를 그대로 가정한 빌드 — #126 병합, #119·#146·#147·#148 Draft 미병합.
     보고에 없는 PR 은 조회 불가로 두므로 새 완료를 만들지 않는다. 이 가정은 이 환경의 실시간 조회가 아니다.

실행: python scripts/gen_mapping.py   (docs/completion-mapping.md 를 다시 쓴다)
"""
import json
import os
import sys
from datetime import datetime
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build  # noqa: E402
import completion  # noqa: E402

OUT = os.path.join(build.ROOT, 'docs', 'completion-mapping.md')
AT = datetime(2026, 10, 27, 16, 0, tzinfo=build.KST)
SLUG = 'bunkering-ai'
STATE_WORD = {'done': '완료', 'now': '진행', 'blocked': '차단', 'side': '참고', 'left': '대기'}


def _record(n, merged, draft, ci=None, head='a' * 40, merge_sha=''):
    repo = 'heechan9/bunkering-ai'
    return {'repo': repo, 'n': n, 'title': f'PR {n}', 'url': f'https://github.com/{repo}/pull/{n}',
            'state': 'closed' if merged else 'open', 'draft': draft, 'merged': merged,
            'mergedAt': '2026-10-17T12:36:43Z' if merged else None, 'mergeSha': merge_sha, 'headSha': head,
            'baseRef': 'main', 'updatedAt': '2026-10-27T06:00:00Z', 'ci': ci or []}


def codex_report(repo, number):
    """직전 Codex 보고에 있는 PR 만 돌려주고 나머지는 조회 실패로 둔다."""
    if (repo, number) == ('heechan9/bunkering-ai', 126):
        return _record(126, True, False, merge_sha='984411c')
    if repo == 'heechan9/bunkering-ai' and number in (119, 146, 148):
        return _record(number, False, True)
    if (repo, number) == ('heechan9/bunkering-ai', 147):
        ci = [{'name': 'Python regression', 'status': 'completed', 'conclusion': 'success', 'url': 'https://github.com/heechan9/bunkering-ai/actions/runs/40363957999',
               'event': 'pull_request', 'at': '2026-10-27T05:00:00Z'}]
        return _record(147, False, True, ci=ci, head='90ef2a6' + '0' * 33)
    raise OSError('보고에 없는 PR')


def _repo_stub(spec, base):
    sha = base['curatedRefs'][spec['id']]
    return {'repo': spec['repo'], 'branch': 'main', 'html': 'https://github.com/' + spec['repo'],
            'head': {'sha': sha, 'date': '2026-10-27T05:00:00Z', 'title': 't', 'url': f'https://github.com/{spec["repo"]}/commit/{sha}'},
            'ci': [], 'merged': [], 'open': []}


def build_after(pr_factory):
    project = next(p for p in build.PROJECTS if p['slug'] == SLUG)
    with open(os.path.join(build.ROOT, 'content', SLUG + '.base.json'), encoding='utf-8') as fh:
        base = json.load(fh)
    with patch.object(build, 'fetch_repo', side_effect=lambda spec: _repo_stub(spec, base)), \
            patch.object(build, 'fetch_pr', side_effect=pr_factory):
        data, pstate = build.build_project(project, {}, AT)
    return {i['id']: i for i in data['items']}


def _urls(cid, card, base_item):
    urls = []
    for e in card.get('evidence', []):
        urls.append((e.get('text', ''), e['href'], card.get('checkedAt')))
    for s in card.get('subtasks', []) + card.get('milestones', []):
        for e in s.get('evidence', []):
            urls.append((e.get('text', ''), e['href'], s.get('checkedAt') or card.get('checkedAt')))
    if not urls and card['evidenceLevel'] != 'curated-only':
        for e in base_item.get('evidence', []):
            if str(e.get('href', '')).startswith('https://'):
                urls.append((e.get('text', ''), e['href'], card.get('checkedAt')))
    seen, out = set(), []
    for t, h, at in urls:
        if h not in seen:
            seen.add(h)
            out.append((t, h, at))
    return out


def _cell(text):
    return str(text).replace('|', '\\|').replace('\n', ' ')


def generate():
    with open(os.path.join(build.ROOT, 'content', SLUG + '.base.json'), encoding='utf-8') as fh:
        base = json.load(fh)
    spec = completion.load_spec(build.ROOT, SLUG)
    completion.validate_spec(spec, base['items'])
    a = build_after(OSError('GitHub 조회 불가'))
    b = build_after(codex_report)
    rows = []
    for item in base['items']:
        cid = item['id']
        card = spec['cards'][cid]
        ia, ib = a[cid], b[cid]
        ca, cb = ia['completion'], ib['completion']

        def verdict(c):
            word = completion.STATUS_WORD[c['status']]
            word += (f' {c["done"]}/{c["total"]}' if c['total'] else '')
            if c.get('milestonesTotal'):
                word += f'; 참고 진행 {c["milestonesDone"]}/{c["milestonesTotal"]}(부모 조건 제외)'
            return word
        urls = _urls(cid, card, item)
        url_cell = '<br>'.join(f'[{_cell(t) or h}]({h}) · {at or "미확인"}' for t, h, at in urls) if urls else '공개 URL 없음 · 미확인'
        remaining = cb['remaining'] or ([] if cb['status'] == 'complete' else ['(하위 조건 없음 — 카드 수동 상태 기준)'])
        if cb['status'] == 'complete':
            remaining = []
        rows.append(
            f'| `{cid}` | {_cell(item["label"])} | {STATE_WORD[item["state"]]} → A {STATE_WORD[ia["state"]]} / B {STATE_WORD[ib["state"]]} '
            f'| {item["countScope"]} (변경 없음) | {completion.KINDS[card["target"]]}: {_cell(card["criterion"])} '
            f'| A {verdict(ca)} / B {verdict(cb)} | {url_cell} | {_cell(" / ".join(remaining)) or "없음"} |')
    required = [i for i in base['items'] if i['countScope'] == 'submission']
    head = [
        '# 병커시유 카드 32개 완료 판정 매핑',
        '',
        '`python scripts/gen_mapping.py` 로 생성한다. 손으로 고치지 않는다(테스트가 최신인지 확인한다).',
        '',
        '- 전 = `content/bunkering-ai.base.json` 의 수동 정리 state. 후 A = GitHub 조회가 모두 실패한 빌드(이 환경의 실측: HTTP 403). 후 B = 2026-10-27 Codex 공개 조회 보고를 가정한 빌드(이 환경의 실시간 조회가 아님; 보고에 없는 PR 은 조회 불가로 두어 새 완료를 만들지 않는다).',
        '- 필수 집계(countScope=submission): 전 ' + f'{sum(i["state"] == "done" for i in required)}/{len(required)}, 후 A '
        + f'{sum(a[i["id"]]["state"] == "done" for i in required)}/{len(required)}, 후 B {sum(b[i["id"]]["state"] == "done" for i in required)}/{len(required)}. 분모와 countScope 는 모든 카드에서 바뀌지 않는다.',
        '- 판정: 완료=모든 하위 조건 충족, 부분 완료=일부만 충족(완료 수에 넣지 않음), 대기=충족 없음, 차단=차단 상태. 하위 조건이 없는 카드는 수동 정리 state 를 따른다.',
        '- 근거 확인 시각이 `미확인` 이거나 URL 이 없으면 공개 근거로 확인되지 않은 수동 정리다.',
        '- 참고 진행(milestones)은 별도 하위 작업 이력이며 부모의 완료 조건·분모에 추가하지 않는다. 고정 head CI 기록은 현재 head CI·병합·채택 완료와 구분한다.',
        '',
        '| 카드 | 라벨 | state 전 → 후 | countScope | 완료 대상과 승인 기준 | 판정 | 공개 근거 URL · 확인 시각 | 남은 조건 |',
        '|---|---|---|---|---|---|---|---|',
    ]
    return '\n'.join(head + rows) + '\n'


if __name__ == '__main__':
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as fh:
        fh.write(generate())
    print('wrote', OUT)
