# GitHub 게시본 정리

사용자 최신 지시: GitHub 업로드, 쉬운 한국어 README, 테스트 및 불필요한 파일 정리. 과거 push 금지 범위는 이번 게시 요청으로 변경됐다.

README를 설계 의도·모델별 역할·5년 CAGR·사용법·검증 범위로 다시 작성했다. 테스트와 일회성 workflow/probe/log 산출물 180파일을 Git 게시 목록에서 제외했다. 자동 승인 검토가 광범위한 로컬 일괄 삭제를 거부했기 때문에 `git rm --cached`를 사용해 실제 파일과 Git 이력을 보존했다. 실질 데이터 삭제는 하지 않았다.

MANIFEST.in에서 제거한 테스트 참조를 제외하고 배포 allowlist를 함께 갱신했다. workspace, 모델 weights, 테스트 원본 및 검증 산출물을 ignore하여 재업로드를 방지했다. runtime/skills/config는 정리 과정에서 수정하지 않았다. 기존 미커밋 runtime와 테스트 WIP7 및 모델 cache는 유지한다.

원격 main은 다른 작업의 v7 capital ranking 변경으로 a9637d8까지 갱신돼 있다. 이를 덮어쓰지 않으며 이번 검증 소스를 별도 `codex/forecast-pretrained-cleanup-20261008` 브랜치로 게시한다. 이전 cursor 원격 브랜치는 존재하지 않았다.

989 PASS 등은 정리 전 실제 검증의 역사적 결과이며 README에 이 범위를 명시했다. 정리한 게시 제안의 깨끗한 복사본에서 fresh wheel/sdist 빌드, 스킬 미러 및 예측 CLI help를 확인했다. 산출물 199/209파일에 tests/cache/DB/weights가 없는지 확인했다. 제외 대상은 테스트127파일과 일회성 도구·로그·원시 검증자료53파일, 총180개다. 자동 승인 검토가 이 대량 제외 상태의 commit을 거부해 구체적인 목록의 추가 승인을 요청했고, 사용자가 `180개 제외하고 업로드`로 명시 승인했다. 이 승인을 기준으로 정리 커밋 및 별도 브랜치 게시를 진행한다.
