"""카드별 '완료'가 무엇을 뜻하는지 정의하고, 공개 GitHub 근거로 판정한다.

content/<slug>.completion.json 이 카드마다 완료 대상(target)·승인 기준(criterion)·하위 작업(subtasks)을 적는다.
이 모듈은 그 규칙을 평가해 카드의 state·substeps·sub·본문과 completion 요약을 한 번에 정한다.
상단 노드·집계·카드 상세는 모두 이 결과(item.state, item.completion)만 읽는다.

원칙
- 자동으로 완료가 될 수 있는 하위 작업은 '코드 반영'(해당 PR 이 main 에 병합) 과 '해당 head 의 CI 성공' 두 종류뿐이다.
  자료 접수·초안·검토·연구 성과·담당자 본인 승인·계약 채택·최종 제출은 수동 정리로만 완료가 된다.
- 병합·CI 는 그 자체로 연구 성과·본인 승인·계약 채택·최종 제출의 완료가 아니다.
- 조회 실패·오래된 캐시는 새 완료를 만들지 않는다. 신선한(이번 빌드에서 성공한) 조회만 새 완료를 만들 수 있다.
- countScope 는 이 모듈이 바꾸지 않는다. 필수 집계의 분모는 그대로다.
- 이미 done 인 카드를 자동으로 되돌리지 않는다. 자동 판정과 어긋나면 '불일치'로 표시하고 재검토를 요청한다.
"""
import json
import os
from datetime import timedelta

KINDS = {
    'code-merge': '코드·문서 반영(main 병합)',
    'ci-pass': '해당 head 의 CI 성공',
    'material-intake': '자료 접수',
    'draft-prepared': '초안 작성',
    'review-done': '검토 완료',
    'research-result': '연구 성과 입증',
    'owner-approval': '담당자 본인 확인·승인',
    'contract-adoption': '계약 채택(C01–C06)',
    'final-submission': '공식 최종 제출',
    'record-history': '과거 기록·참고',
}
AUTO_KINDS = {'code-merge', 'ci-pass'}
RULE_KIND = {'pr_merged': 'code-merge', 'pr_ci_success': 'ci-pass'}
SUB_STATES = ('done', 'now', 'blocked', 'left')
EVIDENCE_LEVELS = {'public': '공개 URL 근거', 'curated-only': '수동 정리(공개 URL 없음·미확인)', 'record': '과거 고정 기록'}


class SpecError(ValueError):
    pass


def spec_path(root, slug):
    return os.path.join(root, 'content', slug + '.completion.json')


def load_spec(root, slug):
    path = spec_path(root, slug)
    if not os.path.exists(path):
        return None
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def pr_ref(text):
    repo, _, number = str(text).rpartition('#')
    if not repo or not number.isdigit():
        raise SpecError(f'PR 참조 형식 오류: {text!r} ("owner/repo#N")')
    return repo, int(number)


def rule_prs(spec):
    """규칙이 참조하는 PR [(repo, number)] — 조회 대상에 합친다."""
    found = []
    for card in (spec or {}).get('cards', {}).values():
        for sub in card.get('subtasks', []):
            rule = sub.get('rule', {})
            if rule.get('type') in RULE_KIND:
                found.append(pr_ref(rule['pr']))
    return list(dict.fromkeys(found))


def validate_spec(spec, items):
    """구성 오류를 모두 모아 SpecError 로 알린다(조용히 넘어가지 않는다)."""
    problems = []
    cards = spec.get('cards')
    if not isinstance(cards, dict):
        raise SpecError('cards 가 객체가 아니다')
    ids = [i['id'] for i in items]
    for missing in sorted(set(ids) - set(cards)):
        problems.append(f'{missing}: 완료 정의가 없다')
    for extra in sorted(set(cards) - set(ids)):
        problems.append(f'{extra}: 카드가 없는데 완료 정의가 있다')
    for cid, card in cards.items():
        where = cid
        for forbidden in ('state', 'countScope'):
            if forbidden in card:
                problems.append(f'{where}: {forbidden} 는 완료 정의에서 바꿀 수 없다')
        if card.get('target') not in KINDS:
            problems.append(f'{where}: target {card.get("target")!r} 이 정의된 종류가 아니다')
        if not card.get('criterion'):
            problems.append(f'{where}: criterion(승인 기준)이 없다')
        level = card.get('evidenceLevel')
        if level not in EVIDENCE_LEVELS:
            problems.append(f'{where}: evidenceLevel {level!r} 오류')
        subs = card.get('subtasks', [])
        milestones = card.get('milestones', [])
        # Supporting receipts/history stay visible without expanding acceptance.
        all_subs = subs + milestones
        sub_ids = [s.get('id') for s in all_subs]
        if len(sub_ids) != len(set(sub_ids)):
            problems.append(f'{where}: subtasks id 중복')
        for sub in all_subs:
            sw = f'{where}/{sub.get("id")}'
            kind, rule = sub.get('kind'), sub.get('rule') or {}
            if kind not in KINDS:
                problems.append(f'{sw}: kind {kind!r} 오류')
            rtype = rule.get('type')
            if sub in milestones and rtype != 'manual':
                problems.append(f'{sw}: 참고 진행(milestones)은 수동 근거 기록만 허용된다')
            if rtype in RULE_KIND:
                if kind != RULE_KIND[rtype]:
                    problems.append(f'{sw}: {rtype} 규칙은 kind={RULE_KIND[rtype]} 하위 작업에만 쓸 수 있다')
                try:
                    pr_ref(rule.get('pr'))
                except SpecError as e:
                    problems.append(f'{sw}: {e}')
                if (sub.get('curated') or {}).get('status', 'left') not in ('done', 'left'):
                    problems.append(f'{sw}: curated.status 는 done/left')
            elif rtype == 'manual':
                if kind in AUTO_KINDS:
                    problems.append(f'{sw}: 자동 종류({kind})는 manual 규칙으로 쓰지 않는다')
                if rule.get('status') not in SUB_STATES:
                    problems.append(f'{sw}: manual.status {rule.get("status")!r} 오류')
                if rule.get('status') == 'done':
                    has_url = any(str(e.get('href', '')).startswith('https://') for e in sub.get('evidence', []))
                    if not (has_url or level == 'curated-only') or not sub.get('checkedAt'):
                        problems.append(f'{sw}: 수동 완료는 공개 URL 증거(또는 evidenceLevel=curated-only 명시)와 checkedAt 이 필요하다')
            else:
                problems.append(f'{sw}: 알 수 없는 규칙 {rtype!r}')
        if card.get('autoComplete'):
            if not subs or any(s.get('kind') not in AUTO_KINDS for s in subs):
                problems.append(f'{where}: autoComplete 는 자동 종류(code-merge/ci-pass) 하위 작업만 가진 카드에만 허용된다')
            if card.get('target') not in AUTO_KINDS:
                problems.append(f'{where}: target={card.get("target")} 은 autoComplete 가 될 수 없다')
    if problems:
        raise SpecError('\n'.join(problems))


def judge_pr(rule, record):
    """신선한 PR 기록 하나로 규칙을 판정한다 → (done|left|mismatch, 이유)."""
    if rule['type'] == 'pr_merged':
        if record['merged']:
            if record.get('baseRef') != rule.get('base', 'main'):
                return 'mismatch', f'병합됐으나 기준 브랜치가 {record.get("baseRef")}'
            want = rule.get('mergeSha')
            if want and not (record.get('mergeSha') or '').startswith(want[:7]):
                return 'mismatch', f'병합 SHA {record.get("mergeSha")} 가 기록 {want[:7]} 와 다름'
            return 'done', f'main 병합 {record.get("mergeSha") or ""}'.strip()
        if record['state'] == 'closed':
            return 'left', '닫힘(미병합)'
        return 'left', '열림·Draft' if record['draft'] else '열림(Draft 아님)'
    ci = record.get('ci') or []
    if not ci:
        return 'left', 'CI 실행 기록 없음'
    if any(r['status'] != 'completed' for r in ci):
        return 'left', 'CI 실행 중'
    bad = [r['name'] for r in ci if r['conclusion'] not in ('success', 'skipped', 'neutral')]
    if bad:
        return 'left', 'CI 실패 ' + ', '.join(bad)
    if any(r['conclusion'] != 'success' for r in ci):
        return 'left', 'CI 성공 미확인(skipped/neutral은 성공을 대신하지 않음)'
    head = rule.get('head')
    if head and not record['headSha'].startswith(head[:7]):
        return 'mismatch', f'현재 head {record["headSha"][:7]} 가 기록 {head[:7]} 와 다름'
    return 'done', 'head CI 성공'


def eval_subtask(sub, prs):
    rule = sub['rule']
    base = {'id': sub['id'], 'label': sub['label'], 'kind': sub['kind'], 'checkedAt': sub.get('checkedAt'),
            'evidence': sub.get('evidence', []), 'auto': rule['type'] in RULE_KIND}
    if rule['type'] == 'manual':
        return dict(base, state=rule['status'], basis='manual', reason='수동 정리', conflict=None)
    repo, number = pr_ref(rule['pr'])
    entry = prs.get(f'{repo}#{number}') or {}
    curated = (sub.get('curated') or {}).get('status', 'left')
    if entry.get('ok') and entry.get('data'):        # 이번 빌드에서 성공한 조회만 신선하다
        verdict, reason = judge_pr(rule, entry['data'])
        if verdict == 'mismatch':
            return dict(base, state='left', basis='live', reason=reason + ' — 재검토 필요',
                        conflict=('수동 정리는 완료, 자동 조회는 ' + reason) if curated == 'done' else None)
        conflict = f'수동 정리는 완료, 자동 조회는 {reason}' if curated == 'done' and verdict != 'done' else None
        return dict(base, state=verdict, basis='live', reason=reason, conflict=conflict)
    why = entry.get('error') or '조회 대상 아님'
    if curated == 'done':                            # 새 완료가 아니라 수동 정리의 기존 완료를 유지
        return dict(base, state='done', basis='curated', reason=f'수동 정리 기준 완료, 자동 확인 불가({why})', conflict=None)
    return dict(base, state='left', basis='none', reason=f'자동 확인 불가({why}) — 완료로 보지 않음', conflict=None)


def evaluate(spec, items, prs):
    """카드 id → 판정. 상태 전이(state)도 여기서 결정한다."""
    by_id = {i['id']: i for i in items}
    out = {}
    for cid, card in spec['cards'].items():
        item = by_id[cid]
        subs = [eval_subtask(s, prs) for s in card.get('subtasks', [])]
        milestones = [eval_subtask(s, {}) for s in card.get('milestones', [])]
        done = sum(s['state'] == 'done' for s in subs)
        if subs:
            status = 'complete' if done == len(subs) else ('partial' if done else 'pending')
        else:
            status = {'done': 'complete', 'blocked': 'blocked'}.get(item['state'], 'pending')
        conflicts = [f'{s["label"]}: {s["conflict"]}' for s in subs if s['conflict']]
        state = item['state']
        if card.get('autoComplete') and status == 'complete' and state != 'done':
            state = 'done'
        if state == 'done' and subs and status != 'complete':
            conflicts.append('카드는 완료로 정리돼 있으나 하위 조건이 모두 충족되지 않았다(자동으로 되돌리지 않음)')
        out[cid] = {'status': status, 'done': done, 'total': len(subs), 'state': state, 'subs': subs,
                    'milestones': milestones,
                    'target': card['target'], 'criterion': card['criterion'], 'level': card['evidenceLevel'],
                    'evidence': card.get('evidence', []), 'checkedAt': card.get('checkedAt'), 'conflicts': conflicts,
                    'autoComplete': bool(card.get('autoComplete'))}
    return out


STATUS_WORD = {'complete': '완료', 'partial': '부분 완료', 'pending': '대기', 'blocked': '차단'}


def describe(result, at, parse_kst, stale_days):
    """카드 본문 끝에 붙는 한 줄. 상단 노드·집계와 같은 판정을 그대로 풀어쓴다."""
    r = result
    word = STATUS_WORD[r['status']]
    if r['total']:
        word += f' {r["done"]}/{r["total"]}'
    left = [s['label'] + (f' [{s["reason"]}]' if s['basis'] in ('live', 'none') else '') for s in r['subs'] if s['state'] != 'done']
    text = f' [완료 판정] 대상: {KINDS[r["target"]]} · 기준: {r["criterion"]} · 판정: {word}'
    if left:
        text += ' · 남은 조건: ' + ' / '.join(left)
    if r.get('milestones'):
        text += ' · 참고 진행(부모 완료 조건 아님): ' + ' / '.join(
            s['label'] + (' [완료]' if s['state'] == 'done' else ' [미완료]') for s in r['milestones'])
    basis = [s for s in r['subs'] if s['state'] == 'done' and s['basis'] in ('curated', 'live')]
    if basis:
        text += ' · 근거: ' + ', '.join(f'{s["label"]}({"자동 확인" if s["basis"] == "live" else "수동 정리"})' for s in basis)
    unverified = [s for s in r['subs'] if s['auto'] and s['basis'] != 'live']
    if unverified:
        why = '; '.join(sorted({s['reason'] for s in unverified}))
        text += f' · 자동 확인 불가 {len(unverified)}건(새 완료로 세지 않음, 수동 정리 기록만 유지): {why}'
    text += f' · 근거 수준: {EVIDENCE_LEVELS[r["level"]]}'
    when = parse_kst(r.get('checkedAt'))
    if r['subs'] and all(s['basis'] == 'live' for s in r['subs']):
        text += ' · 근거 확인 이번 빌드의 GitHub 조회'
    elif when:
        age = at - when
        text += f' · 근거 확인 {r["checkedAt"]}' + (' · 오래됨' if age > timedelta(days=stale_days) else '')
    if r['conflicts']:
        text += ' · 불일치: ' + '; '.join(r['conflicts'])
    return text + '.'


def _substep(sub):
    out = {'label': sub['label'], 'state': sub['state'], 'completionRole': 'acceptance'}
    href = next((e['href'] for e in sub['evidence'] if str(e.get('href', '')).startswith('https://')), None)
    if href:
        out['href'] = href
    return out


def apply(spec, items, prs, at, parse_kst, stale_days):
    """items 를 제자리에서 갱신하고 판정 dict 를 돌려준다. countScope·label·title·lane 은 건드리지 않는다."""
    results = evaluate(spec, items, prs)
    for item in items:
        r = results[item['id']]
        item['state'] = r['state']
        if r['subs'] or r['milestones']:
            item['substeps'] = [_substep(s) for s in r['subs']]
            for s in r['milestones']:
                step = _substep(s)
                step['label'] = '참고 진행 · ' + step['label']
                step['completionRole'] = 'supporting'
                item['substeps'].append(step)
        if r['status'] == 'partial':
            item['sub'] = (item.get('sub') or '') + f' · 하위 {r["done"]}/{r["total"]} 완료'
        item['completion'] = {'status': r['status'], 'done': r['done'], 'total': r['total'], 'target': r['target'],
                              'milestonesDone': sum(s['state'] == 'done' for s in r['milestones']),
                              'milestonesTotal': len(r['milestones']),
                              'level': r['level'], 'conflict': bool(r['conflicts']),
                              'remaining': [s['label'] for s in r['subs'] if s['state'] != 'done'],
                              'unverified': sum(1 for s in r['subs'] if s['auto'] and s['basis'] != 'live')}
        item['body'] = (item.get('body') or '').rstrip() + describe(r, at, parse_kst, stale_days)
    return results
