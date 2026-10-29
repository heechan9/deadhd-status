# 프로젝트 상태판 (deadhd)

병커시유·적대적 AI·FabGuard AI 프로젝트의 진행 상황을 [deadhd](https://github.com/lcalmsky/deadhd) 디자인으로 보여주는 정적 페이지다. GitHub Actions 가 1시간마다(그리고 수동 실행 시) 공개 GitHub 기록을 다시 조회해 GitHub Pages 에 배포한다.

| 페이지 | 조회 대상 |
|---|---|
| `bunkering-ai.html` | `heechan9/bunkering-ai` |
| `adversarial-ai.html` | 공식 `th0oel/AdversarialAI_Security`, 개인 포크 `heechan9/AdversarialAI_Security` (공식 미반영으로 구분) |
| `fabguard-ai.html` | `heechan9/fabguard-ai` · 합성 3D main 반영과 미병합 Draft, 검증 한계 구분 |

FabGuard는 제출 계약을 정의하지 않은 근거 상태판으로 완료율을 표시하지 않는다. 기존 두 프로젝트의 제출 분모·완료 판정은 변경하지 않는다.

## 원칙

- 공개 GitHub 기록만 사용한다. 로컬 경로·IP·대화 기록·비공개 링크·토큰은 게시하지 않는다.
- 자동 조회(맨 위 줄)는 main HEAD·최근 병합 PR·열린 PR·main CI 만 다룬다. **병합이나 CI 성공은 실험·연구 완료로 표시하지 않는다.**
- 그 아래 항목은 `content/*.base.json` 의 수동 정리로, 각 파일의 `curatedRefs`(공식·포크별 SHA, 기존 단일 저장소는 `curatedSha`) 시점 공개 문서에 근거한다. main 이 그 뒤로 바뀌면 페이지에 '정리 이후 변경 · 검토 필요'가 표시된다.
- 조회가 실패하면 직전 배포의 `state.json` 에서 마지막 성공 결과를 유지하고 '갱신 실패'를 표시한다.
- **카드에 연결된 PR 의 실제 상태**: 수동 카드의 `evidence` 에 PR 링크가 있으면(또는 카드에 `"linkedPrs": ["owner/repo#N"]` 을 적으면) 매시간 해당 PR 의 열림·Draft·병합·닫힘과 현재 head 의 워크플로 결과를 조회해 카드 본문 끝 `[자동 조회 …]` 줄과 증거 링크 옆에 덧붙인다. 카드에 `"liveStatus": false` 를 쓰면 제외한다. 수동 검토 때 고정한 head(`curatedPrs`)와 달라지면 '수동 검토 head 이후 변경'이 표시된다. 연결 PR 은 프로젝트당 60건까지 조회한다.
- **카드 완료는 규칙으로만 바뀐다**: `content/<slug>.completion.json` 이 카드마다 완료 대상(코드 반영·자료 접수·검토·연구 성과·본인 승인·계약 채택·최종 제출)과 승인 기준, 하위 조건을 정하고 `scripts/completion.py` 가 판정한다. 자동으로 완료가 되는 것은 '코드 반영(해당 PR 이 main 에 병합)'을 명시한 카드·하위 작업뿐이다. PR 병합이나 CI 성공은 연구 성과·팀원 본인 확인·계약 채택·최종 제출의 완료가 아니며, 그 하위 조건은 수동 검토로만 바뀐다. 복합 카드는 일부만 충족되면 '부분 완료'(노드 점선·상단 요약·카드 하위 항목)로 보이고 필수 집계 분자에 들어가지 않는다. `countScope`·분모는 어떤 경우에도 자동으로 바뀌지 않는다. 카드별 판정표는 `docs/completion-mapping.md`(`python scripts/gen_mapping.py` 로 생성).
- **오래됨·실패 표시**: PR 조회가 실패하면 마지막 성공 기록과 경과 시간을 카드에 표시하고(3시간을 넘으면 '오래됨'), 기록이 없으면 '이전 성공 기록 없음'으로 표시한다. 실패는 맨 위 줄('일부 실패')·'PR 상태 갱신 실패' 항목·`state.json` 에 남는다. 수동 내용 검토 시각(`curatedAt`)이 3일을 넘거나 해석할 수 없으면 '수동 검토 오래됨'을 표시한다. 기록 없음(실행 기록 없음)은 CI 성공으로 쓰지 않는다.

## 구성

`subtasks`는 부모 카드의 완료 조건이다. `milestones`는 별도 접수·초안·고정 head CI 등 참고 하위 진행으로, 카드 상세와 요약에는 보이지만 부모의 완료 조건·분모에는 넣지 않는다. 외부 지원 최종 로그·계약 채택을 정식 팀원의 1차 접수 완료 조건으로 추가하지 않는다. CI 실행 결과가 skipped/neutral인 것은 성공으로 판정하지 않는다(성공한 실행 내부의 개별 테스트 skip 수와는 별개).

- `scripts/build.py` — 조회·병합·렌더링 (표준 라이브러리만 사용)
- `content/` — 수동 정리 내용
- `vendor/deadhd/` — deadhd v1.9.0 원본 파일 (MIT, `THIRD_PARTY_NOTICES.md` 참고)
- `.github/workflows/pages.yml` — 매시 23분(UTC)·수동·push 시 빌드와 Pages 배포

로컬 확인: `python3 -m unittest discover -s scripts -p 'test_*.py'`(네트워크 없음) 후 `python3 scripts/build.py` 로 `site/` 를 만들어 연다.

적대적 AI는 본 연구 완료 범위, 제출 이후 확장, 잔여 재현·검증·공식 통합을 분리한다. `curatedAt`은 수동 내용 검토 시각이고 자동 조회 시각과 별개다. `curatedPrs`에 고정한 PR head가 바뀌거나 열린 목록에서 사라지면 재검토를 표시하며 자동으로 완료 처리하지 않는다.

