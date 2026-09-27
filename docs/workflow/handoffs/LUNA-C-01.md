# LUNA-C-01 — C 담당 R12–13 및 브리핑 안전 보완 인계

- **작업 ID**: LUNA-C-01 (GPT6-LUNA-TRANSFER-02의 C 담당 이관)
- **요구사항**: R10–13, R17 (부분 구현; 아래 미완료 의존성 참조)
- **설계 기준**: DESIGN-2026-09-23-v0.1, requirements REQ-2026-09-23-v1
- **시작 HEAD**: `1d5f2f20339ff334af799ad798019ccdcbbd90d7`
- **브랜치**: `codex/gpt6-luna-c`
- **완료 HEAD**: `098a0b855053060c6f1bbb296b997fbbd358f600`
- **커밋**: `adfdbae` (R12–13), `098a0b8` (R10–11/R17 브리핑)
- **테스트 데이터**: SEC 13F XML 및 계약 객체 synthetic fixture만 사용. 개인 DB·credential 사용 없음.

## 변경

- SEC 13F XML에서 수량 또는 `SH`/`PRN` 종류가 없거나 유효하지 않으면 해당 행을 0 수량으로 만들지 않고 제외하며 coverage를 partial로 표시한다.
- `ADD_NEW_HOLDINGS` 정정은 중복 종목을 덮어쓰지 않는다. 상충 값은 unresolved로 남기고, 유형 미확정 정정은 부분 행을 적용하지 않아 마지막 명확한 snapshot을 보존한다.
- `13F-NT`는 기존 보유 세트를 지우지 않는다. holdings snapshot을 입증하지 않으므로 effective set을 unresolved로 표시해 비교를 차단한다.
- 비교 가능한 종목 관측이 없으면 방향·coverage 결과를 중립 0으로 채우지 않고 `None`으로 유지한다. Filing 공개 timestamp가 비교 계약에 연결되지 않아 정보 지연 일수도 계산 불가로 둔다. 분기 말일로 실제 공개 나이를 추정하던 동작을 제거했다.
- 브리핑은 기존 5개 섹션 순서를 유지한다. 적격 가격·가치평가 및 승인 정책 provenance가 완전히 결속되지 않은 경우 WAIT를 유지하고, 진입·축소 구간 및 금액·수량을 `계산 불가`로 표시한다. 13F 점수는 미검증 보조 근거로만 표시한다.

## 실행한 검증

`C:/Users/lsn/lsn-asset-mng-skills/.venv/Scripts/python.exe`를 사용하고 작업 worktree의 `runtime`을 `PYTHONPATH`로 지정했다.

```powershell
$env:PYTHONPATH='runtime'
C:/Users/lsn/lsn-asset-mng-skills/.venv/Scripts/python.exe -m unittest tests.unit.test_r12_sec_13f tests.unit.test_r13_validation tests.decisions.test_briefing tests.decisions.test_action tests.decisions.test_builder_briefing -v
```

결과: **41 tests, OK**. 새 synthetic 검사는 notice-only filing, 미확정 정정 덮어쓰기 방지, 누락/비유한 수량, 관측 결측 표시, 5섹션 브리핑 및 타입 의미를 확인하지 않은 일반 계산값 비노출을 포함한다.

## 총괄 독립 재검토 수정

- 총괄 검토에서 `CalculationRecord.calculation_name`만으로 값이 적격 현재가·가치평가·거래 규모인지 입증되지 않는 점을 지적했다. 이에 일반 계산값의 상세 근거 노출을 제거했다. 입력 계산들은 lineage 검증에만 사용하고, 의미 whitelist/적격성 계약이 추가되기 전까지 출력 숫자는 표시하지 않는다.
- 수정 검증: `test_briefing_available_wait`는 해당 계산 숫자가 상세 및 가격·행동 표에 나타나지 않는지 확인한다. tzdata 포함 interpreter로 위 5개 테스트 모듈을 재실행해 **41 tests, OK**.

## 미실행 검증 및 남은 의존성

- SEC live 응답, 전체 SEC XML schema vintage/XSD, 실제 종목 식별 mapping은 검증하지 않았다. 원 CUSIP·클래스 등이 있는 원문 보존 수준이며 ticker/ADR/기초자산 mapping은 별도 근거가 필요하다.
- 비교 객체에 실제 filing `public_available_at`을 잇는 계약이 없어 13F 정보 나이 계산은 계속 unavailable이다. Point-in-time 과거 데이터셋·사전등록 baseline·비용 포함 기간 외 검증도 없어 R13 점수는 계속 `UNVALIDATED`, 거래 게이트는 disabled다.
- A의 적격 현재가격 및 DCF/가치 결과, 승인된 개인 정책 provenance 및 개인 상태 pin 결합은 아직 없다. 따라서 R10–11의 실제 가격 판단과 개인 규모 산출은 미완료이며 공개 action은 WAIT/no tranche를 유지한다. `calculate_budget_arithmetic`는 독립 순수 산술 전구체이고 전체 의사결정 경로가 아니다.
- 첫 테스트 실행은 개발 기본 Python에서 5건의 환경/픽스처 실패를 보였다. 이후 총괄이 안내한 tzdata 포함 interpreter로 동일 관련 스위트와 reporting builder 검증을 실행해 41건 모두 통과했다. 전체 저장소 회귀는 실행하지 않았다.

## 소유권

변경 파일은 C 담당인 `providers/sec_13f.py`, `institutional/{models,normalize,scoring}.py`, `decisions/briefing.py`와 해당 C 전용 unit/decision tests, 이 handoff뿐이다. 공통 계약·A/B 파일·개인 DB는 수정하지 않았다. 총괄은 이 branch를 검토한 후 자신의 통합 절차로 반영한다.
