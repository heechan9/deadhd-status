# 프로젝트 상태판 (deadhd)

병커시유와 적대적 AI 프로젝트의 진행 상황을 [deadhd](https://github.com/lcalmsky/deadhd) 디자인으로 보여주는 정적 페이지다. GitHub Actions 가 1시간마다(그리고 수동 실행 시) 공개 GitHub 기록을 다시 조회해 GitHub Pages 에 배포한다.

| 페이지 | 조회 대상 |
|---|---|
| `bunkering-ai.html` | `heechan9/bunkering-ai` |
| `adversarial-ai.html` | 공식 `th0oel/AdversarialAI_Security`, 개인 포크 `heechan9/AdversarialAI_Security` (공식 미반영으로 구분) |

## 원칙

- 공개 GitHub 기록만 사용한다. 로컬 경로·IP·대화 기록·비공개 링크·토큰은 게시하지 않는다.
- 자동 조회(맨 위 줄)는 main HEAD·최근 병합 PR·열린 PR·main CI 만 다룬다. **병합이나 CI 성공은 실험·연구 완료로 표시하지 않는다.**
- 그 아래 항목은 `content/*.base.json` 의 수동 정리로, 각 파일의 `curatedRefs`(공식·포크별 SHA, 기존 단일 저장소는 `curatedSha`) 시점 공개 문서에 근거한다. main 이 그 뒤로 바뀌면 페이지에 '정리 이후 변경 · 검토 필요'가 표시된다.
- 조회가 실패하면 직전 배포의 `state.json` 에서 마지막 성공 결과를 유지하고 '갱신 실패'를 표시한다.

## 구성

- `scripts/build.py` — 조회·병합·렌더링 (표준 라이브러리만 사용)
- `content/` — 수동 정리 내용
- `vendor/deadhd/` — deadhd v1.9.0 원본 파일 (MIT, `THIRD_PARTY_NOTICES.md` 참고)
- `.github/workflows/pages.yml` — 매시 23분(UTC)·수동·push 시 빌드와 Pages 배포

로컬 확인: `python3 scripts/build.py` 후 `site/` 를 연다.

적대적 AI는 본 연구 완료 범위, 제출 이후 확장, 잔여 재현·검증·공식 통합을 분리한다. `curatedAt`은 수동 내용 검토 시각이고 자동 조회 시각과 별개다. `curatedPrs`에 고정한 PR head가 바뀌거나 열린 목록에서 사라지면 재검토를 표시하며 자동으로 완료 처리하지 않는다.
