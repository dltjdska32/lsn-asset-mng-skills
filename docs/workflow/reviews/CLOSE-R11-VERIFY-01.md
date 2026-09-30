# CLOSE-R11 별도 Codex 최종 검증

- 검증 세션: `/root/close_r11_final_verify_01`. A/B 구현·총괄 통합·`/root/close_r11_review_01` 독립 검토와 다른 Codex 세션.
- 정확한 대상 HEAD: `f711337ea1cfa56b22aa4f1a58347d76488486b7`; 마지막 runtime code source: `9fa62bd30fc5214b2ee275748e28515babe8f15f`. 두 커밋 사이에는 검토·상태·인계 문서만 추가됐다.
- 범위: D12 B 시세/DCF 출처, 고정 개인 원장 투영, 비거래 수량·보고서 release, 일반 Phase4/5의 일요일 마지막 유효 종가. 개인 실제 DB·주문·live provider는 사용하지 않았다.
- 판정: **검증된 안전 대기 범위 PASS, 새 P1/P2 없음. R11 실사용 행동 수치 완료 아님.**

## 독립 실행 결과

1. 대상 SHA의 별도 Git archive에서 추적 파일 **526/526**의 blob 내용이 일치했다(Windows checkout CRLF 정규화). 새 wheel/sdist가 빌드됐고 핵심 runtime 3개 파일의 source/wheel/sdist 내용이 일치하며 wheel에 DB 파일이 없었다.
2. 첫 전체 테스트는 **698 실행, 1 실패, 1 skip**이었다. archive 자체에는 `.git`이 없어 `.env.example`의 `git check-ignore` 검사가 상위 원본 저장소의 `workspace/cache/` ignore 규칙을 상속한 격리 환경 오류였다. archive 안에 독립 `git init` 경계를 만든 후 같은 전체 suite는 **698 OK(skip1)**였다. 첫 실패를 제품 코드 통과로 숨기지 않는다.
3. 별도 집중 **38/38**, 검증 세션이 직접 만든 합성 반례 **11/11** 통과. 임의 달력, 오래된 FRESH, evidence/market observed·claimed/provider 불일치, 자기작성 quote/DCF URL, 가짜 ID/flag 수량 release를 검증했다. 합성 개인 DB는 조회 전후 SHA가 같았고 원본 저장소는 깨끗했다.
4. 일요일의 앞선 정상 거래일 종가는 일반 Phase4/5 분석에 유지된다. D12 행동용 quote/DCF는 인증 가능한 원문 receipt가 없으면 WAIT이며 보고서의 진입가·예산·수량은 노출되지 않는다.

## 남은 제한

인증 가능한 시세·DCF source-content receipt, 개인 시가/FX·비상자금/예정 지출·미체결 주문 예약, 수수료/거래 단위의 실사용 결속이 없다. 사용자별 추가매수·축소 가격/금액/수량은 **WAIT**다. 이 검증은 공개 공급자 원문의 실시간 진위, pinned September 2026 범위 밖 거래일, 기본 CLI host 자동 연결을 입증하지 않는다.
