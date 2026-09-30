# PREP-C: SEC 13F 원문 및 스키마 분석 보고서

- **작업 ID**: PREP-C
- **요구사항 ID**: REQ-v1 R12–13
- **설계 문서**: DESIGN-v0.1 (§5 R12–R13)
- **세션**: Gemini Implementation Session C
- **기준 브랜치 / 커밋**: `codex/gemini-c` / `68fab98`
- **조회 주체**: 총괄 (웹 조회 및 HTTP 수집은 총괄이 대행 수행함; Gemini C는 worktree 내 파일 및 총괄 수집 자료만 직접 분석)
- **작성 일시**: 2026-09-23T16:55:00+09:00

---

## 1. 공식 원문 출처 및 확인 기록

| 구분 | 공식 URL / 참조 경로 | 확인 일시 (UTC/KST) | 확인 주체 | 확인 내용 요약 |
|---|---|---|---|---|
| SEC EDGAR APIs | `https://www.sec.gov/search-filings/edgar-application-programming-interfaces` | 2026-09-23 | 총괄 | Submissions API (`/submissions/CIK{cik10}.json`), Company Facts 구조 및 10자리 CIK, recent/files 분할 구조 |
| SEC Form 13F FAQ | `https://www.sec.gov/rules-regulations/staff-guidance/division-investment-management-frequently-asked-questions/frequently-asked-questions-about-form-13f` | 2026-03-06 (공식 갱신) / 2026-09-23 확인 | 총괄 | 2023-01-03 자로 13F 개정 시행. 가치 보고 단위(달러 단위 반올림) 변경, 정정 분류(Restatement vs Adds New Holdings), 기밀유지(Confidential Treatment) 만료 처리 |
| SEC Developer Policy | `https://www.sec.gov/about/developer-resources` | 2026-09-23 | 총괄 | 초당 10회 요청 제한, 선언적 User-Agent 헤더 필수(`User-Agent: Sample Company Name AdminContact@<sample company domain>.com`). 임의 인증/연락처 발명 금지 |
| Berkshire Submissions 수집본 | `workspace/runs/source-inputs/sec_berkshire_submissions.json` (로컬) | 2026-09-23 | Gemini C 직접 확인 | CIK `0001067983` 실제 EDGAR API 응답 JSON. 1,000개 recent 제출 행 및 추가 파일(`CIK0001067983-submissions-001.json`) 메타데이터 확인 |
| EDGAR Archive XML/Index | `https://www.sec.gov/Archives/edgar/data/...` | 2026-09-23 | 총괄 | **HTTP 403 Forbidden 발생**. 실제 raw information table XML 실시간 다운로드 검증은 미완료 상태임 |

---

## 2. `sec_berkshire_submissions.json` 실측 관측 스키마

총괄이 수집한 `sec_berkshire_submissions.json` 원본 데이터로부터 관측된 실제 EDGAR Submissions 스키마 구조는 다음과 같다:

### (1) 최상위 엔티티 메타데이터
- `cik`: 10자리 문자열 (예: `"0001067983"`)
- `entityType`: `"operating"`
- `name`: `"BERKSHIRE HATHAWAY INC"`
- `tickers`: `["BRK-B", "BRK-A"]`
- `exchanges`: `["NYSE", "NYSE"]`
- `fiscalYearEnd`: `"1231"`
- `filings`: 하위 `recent` 및 `files` 객체 보유

### (2) `filings.recent` 컬럼형(Columnar Array) 구조
`filings.recent`는 각 필드가 동일한 길이(Berkshire 기준 1,000개)의 배열을 갖는 구조이다:
- `accessionNumber`: `string` (예: `"0001193125-26-352200"`), 20자리(18자리 숫자 + 하이픈 2개)
- `filingDate`: `string (YYYY-MM-DD)` (공식 접수 공시일, 예: `"2026-08-14"`)
- `reportDate`: `string (YYYY-MM-DD)` (보유 기준 분기말일, 예: `"2026-06-30"`, 보고서에 따라 빈 문자열 `""`)
- `acceptanceDateTime`: `string (ISO-8601 UTC)` (정확한 수락 시각, 예: `"2026-08-14T20:05:04.000Z"`)
- `act`: `string` (`"34"` 등)
- `form`: `string` (`"13F-HR"`, `"13F-HR/A"`, `"13F-NT"`, `"10-Q"`, `"10-K"`, `"4"` 등)
- `fileNumber`: `string` (13F 제출건은 `"028-04545"`와 같이 `028-` 접두어를 가짐)
- `filmNumber`: `string` (예: `"261281164"`)
- `items`: `string`
- `size`: `int` (문서 바이트 크기)
- `isXBRL`: `0` 또는 `1` (13F는 XML 기반이지만 인라인 XBRL이 아니므로 `isXBRL=0`)
- `isInlineXBRL`: `0` 또는 `1`
- `primaryDocument`: `string` (예: `"xslForm13F_X02/primary_doc.xml"`, 과거 문서는 `"xslForm13F_X01/primary_doc.xml"`, `"tv0025-berkshirehathawayincc.htm"`, 또는 `.txt`)
- `primaryDocDescription`: `string` (예: `""`, `"PRIMARY DOCUMENT"`)

### (3) `filings.files` 분할 파일(Historical Partition)
- 과거 제출건이 1,000개를 초과할 때 과거 분할 파일 목록이 제공됨:
  - `name`: `"CIK0001067983-submissions-001.json"`
  - `filingCount`: `1398`
  - `filingFrom`: `"1998-08-10"`, `filingTo`: `"2017-01-10"`
- 대규모 히스토리 조회가 필요할 경우 해당 partition 파일을 순차 병합해야 함.

---

## 3. SEC Form 13F 원문 규격 및 핵심 기술 명세

SEC 규정(Release No. 34-95148), 13F FAQ 및 EDGAR XML 사양 분석 결과:

### (1) 2023-01-03 Value 단위 변경 (가장 중요한 계산 함정)
- **2023-01-03 이전 규정**:
  - Information Table의 `VALUE` 열은 **천 달러 단위($1,000 단위)** 로 보고됨 (nearest $1,000, 즉 끝의 세 자리 000 생략).
  - 예: 원본에 `1234`로 기재되어 있으면 실제 가치는 `$1,234,000`임.
- **2023-01-03 이후 개정 규정**:
  - Form 13F 현대화 규정에 따라 가치를 **1달러 단위(nearest US dollar)** 로 반올림하여 기재.
  - 예: 원본에 `1234567`로 기재되어 있으면 실제 가치는 `$1,234,567`임.
- **Primary Document 스타일시트 및 스키마 버전 차이**:
  - 관측된 Berkshire 제출 데이터에서 2023년 이전은 `xslForm13F_X01/primary_doc.xml`, 2023년 이후는 `xslForm13F_X02/primary_doc.xml`로 스타일시트 버전이 분기됨.
  - **파서 판별 규칙**:
    1. 문서의 XML 네임스페이스 및 `primaryDocument` 경로(`X01` vs `X02`) 검사.
    2. `reportDate` 및 `filingDate`가 `2023-01-03` 이전인지 이후인지 판정.
    3. `2023-01-03` 이전: `value_scale = 1000` (원값 × 1,000 적용).
    4. `2023-01-03` 이후: `value_scale = 1` (원값 그대로 달러 적용).
    5. 모호하거나 규격과 일치하지 않는 경우 `INVALID_SCALE` 에러로 격리하고 임의 추정 금지.

### (2) 정정(Amendment) 유형과 합성 체인
Form `13F-HR/A` 제출 시 Cover Page에 명시되는 정정 유형:
1. **`RESTATEMENT` (재작성/전부 대체)**:
   - 이전 공시의 오류를 수정하거나 전체를 다시 제출함.
   - **적용 규칙**: 동일 manager 및 분기에 대해 cutoff 이전 최종 RESTATED 공시가 확인되면 해당 범위의 원본 보유 내역을 **완전 대체(replace)** 함.
2. **`NEW HOLDINGS` (신규 보유 추가)**:
   - 기밀유지(Confidential Treatment) 만료 등의 사유로 이전에 누락되었던 추가 보유 내역을 사후 공시함.
   - **적용 규칙**: 원본 공시의 보유 목록에 추가 보유 항목을 **합성(merge)** 하되, CUSIP/클래스 중복 여부 및 manager 범위를 검증함. 중복 키 발생 시 임의 덮어쓰기를 금지하고 `UNRESOLVED_CONFLICT`로 격리.
3. **정정 체인 미확인 시 상태**:
   - 베이스 accession과의 연결 고리가 불분명하거나 범위가 특정되지 않으면 `AMENDMENT_CHAIN_UNCONFIRMED`로 표시하고 단일 확정 포트폴리오로 합성하지 않음.

### (3) Information Table XML 스키마 상세
Information Table XML (`<informationTable>`) 내부의 `<infoTable>` 반복 항목 필드:
- `<nameOfIssuer>`: 발행사 명칭 (문자열)
- `<titleOfClass>`: 주식/증권 종류 (예: `"COM"`, `"CL A"`, `"SPONSORED ADR"` 등)
- `<cusip>`: 9자리 CUSIP 식별자
- `<value>`: 보고 가치 (숫자, 2023년 이후 달러, 이전 천달러)
- `<shrsOrPrnAmt>`:
  - `<sshPrnamt>`: 보유 수량 (정수 또는 소수)
  - `<sshPrnamtType>`: **`SH` (Shares)** 또는 **`PRN` (Principal Amount)**. 전환사채 등 원금형 증권(`PRN`)을 보통주 주식 수(`SH`)와 단순 합산하는 것을 엄격히 차단해야 함.
- `<putCall>`: 옵션 여부 (`PUT` 또는 `CALL`). 주식 현물 보유와 파생 옵션 계약을 동일 종목으로 묶어 합산해서는 안 됨.
- `<investmentDiscretion>`: 운용 재량권 (`SOLE`, `DEFINED`, `OTHER`).
- `<otherManager>`: 공동 운용 관리자 식별 번호 (이중 계산 방지 필수).
- `<votingAuthority>`: 의결권 (`<Sole>`, `<Shared>`, `<None>`).

### (4) 기밀유지 요청(Confidential Treatment, CT)과 부재(Absence)
- 기관은 신규 매집 중 시장 충격을 방지하기 위해 SEC에 특정 종목의 공시 유예(Confidential Treatment)를 요청할 수 있음.
- 유예 승인 시 원본 13F에서는 해당 종목이 완전히 누락됨.
- 유예 만료 후 `13F-HR/A (Adds New Holdings)`로 뒤늦게 공시됨.
- **포트폴리오 비교 정책상의 불변식**:
  - 13F 보고서에 특정 종목이 없다는 사실(`NOT_REPORTED`)이 해당 분기에 해당 주식을 보유하지 않았거나 전량 매도했다는 것을 뜻하지 않음 (`Absence ≠ Sold`).
  - 기밀유지 또는 보고 누락 가능성이 있으므로, 결측치는 `0`으로 채우지 않고 `NOT_REPORTED` 상태를 보존함.

### (5) 공개시점(Public Availability)과 시점 누출(Point-in-Time Leakage) 방지
- **`reportDate` (보고 대상 분기말)**: 예컨대 2026-06-30.
- **`acceptanceDateTime` (EDGAR 실제 접수/공개시각)**: 예컨대 2026-08-14T20:05:04.000Z.
- **`filingDate`**: 2026-08-14.
- 13F 공시는 분기말 이후 최대 45일의 시차가 존재함.
- **경계 불변식**:
  - 특정 분석 cutoff 시점 `T`에서 사용 가능한 13F 데이터는 `acceptanceDateTime <= T`인 공시만 해당함.
  - `reportDate <= T`라는 이유로 8월에 나온 공시를 7월 분석에 사용하는 것은 심각한 **미래 정보 누출(Look-ahead leak)** 임.
  - 13F 관측값은 항상 `observed_at = reportDate`와 `public_available_at = acceptanceDateTime`을 분리하여 보존함.

---

## 4. 포트폴리오 비교 및 지표 산출 정책

### (1) 동일성 비교 전제조건 (Strict Comparability)
비교 가능한 두 분기 ($t-1, t$)는 다음 조건이 모두 충족될 때만 지표를 계산함:
- 동일한 관리자 CIK (`manager_cik`)
- 동일한 보고 범위 및 discretion
- 동일한 종목 식별자(CUSIP) 및 주식 클래스
- 동일한 수량 단위 (`quantity_type`: `SH`는 `SH`끼리만, `PRN`은 `PRN`끼리만)
- 분할/병합 등 Corporate Action 계수가 보정된 수량 기준

### (2) 산출 지표
- **수량 변화량**: $\Delta Q = Q_t - Q_{t-1}$ (주식분할 정합화 완료 후)
- **수량 변화율**: $Q_{t-1} > 0$일 때 $\frac{\Delta Q}{Q_{t-1}}$
- **보고 포트폴리오 내 비중**:
  $$\text{reported\_weight}_i = \frac{\text{value}_i}{\sum_{j \in \text{eligible}} \text{value}_j}$$
  *(주의: 분모는 13F에 보고된 적격 지분증권 총액이며, 기관의 전체 AUM, 비상장 자산, 채권, 현금, 숏 포지션을 포함한 순자산이 아님을 명시)*
- **비중 변화**: $\Delta \text{weight}_i = \text{weight}_{i, t} - \text{weight}_{i, t-1}$

---

## 5. 미검증 사항 및 현 단계의 기술적 제한

1. **EDGAR Archive Information Table live HTTP 검증 미완료**:
   - 총괄의 HTTP 조회 시 SEC EDGAR 아카이브 엔드포인트(`https://www.sec.gov/Archives/edgar/data/...`)에서 **HTTP 403 Forbidden**이 반환되었음.
   - 이는 SEC EDGAR 정책상 요구되는 User-Agent 헤더 양식 준수 및 공식 접근 설정이 아직 런타임 수집기에 적용되지 않았기 때문임.
   - 따라서 실제 live 네트워크 통신을 통한 raw XML 파싱 테스트는 수행되지 않았으며, 현재 단계에서는 총괄이 확보한 submissions JSON 메타데이터와 공식 XSD/FAQ 사양만을 근거로 파서 규격을 수립함.
2. **대규모 역사 데이터셋 미검증**:
   - 과거 다년간의 13F 전체 데이터를 파싱하거나 대규모 기관 풀에 대한 백테스트를 수행하지 않았음.
3. **실거래 가중치 및 점수 모델 미검증**:
   - 13F 보유 변화나 비중 증가를 직접적인 매매 신호 가중치로 사용하는 것은 검증되지 않았음.
   - **`score_status = UNVALIDATED` 게이트 엄격 유지**: R13 규약에 따라 누출 없는 point-in-time 백테스트 프로토콜이 독립 검증을 통과하기 전까지, 13F 데이터는 브리핑 본문의 **정성적/보조적 설명 자료**로만 제시되며 계량 투자 판단이나 수량/금액 산출식에 직접 투입되지 않음.

---

## 6. 총괄 후속 실행을 위한 HTTP 엔드포인트 및 원문 취득 가이드

추후 총괄 세션에서 공식 아카이브 XML 수집 및 fixture 확보 시 준수해야 할 절차:

### (1) 엔드포인트 규격
1. **Submissions API**:
   - `GET https://data.sec.gov/submissions/CIK{cik.zfill(10)}.json`
   - 헤더: `User-Agent: {ApprovedAppName} {ContactEmail}` (예: 공식 승인된 사용자 에이전트)
2. **Accession 디렉터리 및 원문 파일 취득**:
   - URL 패턴: `https://www.sec.gov/Archives/edgar/data/{cik_without_zeros}/{accession_no_without_dashes}/`
   - 문서 번호와 파일 매핑:
     - `filings.recent.primaryDocument[i]`가 `"xslForm13F_X02/primary_doc.xml"`인 경우 실제 제출 폴더의 XML 파일명은 통상 `primary_doc.xml` 또는 submission XML에 포함된 information table 파일(예: `infotable.xml`)임.
     - 디렉터리의 `index.json` 또는 `accession-index.htm`을 파싱하여 `form13fInfoTable.xml` 또는 `information_table.xml`을 특정해야 함.

### (2) 문서 선택 필터링 규칙 (13F 전용)
- `form in ("13F-HR", "13F-HR/A")`
- `fileNumber`가 `"028-"`로 시작하는 항목
- `acceptanceDateTime <= cutoff` 조건을 만족하는 항목 중 가장 최신 접수건 선택
- 만약 선택된 항목이 `13F-HR/A`인 경우, 이전 동일 분기 `13F-HR` 및 선행 정정건과의 체인 관계 확인

---

## 7. 결론 및 대기

- PREP-C 조사를 통해 SEC 13F의 2023-01-03 단위 변경, 정정 유형(RESTATEMENT vs NEW HOLDINGS), XML 스키마 네임스페이스 및 필드 구조, acceptanceDateTime 기반 point-in-time 분리 규칙을 모두 명확히 확정함.
- 런타임/테스트/공통계약 코드는 수정하지 않았으며, 안전 경계와 격리 규칙을 준수함.
- 공통계약(`CONTRACT-01`) 커밋 및 총괄의 후속 지시를 대기함.
