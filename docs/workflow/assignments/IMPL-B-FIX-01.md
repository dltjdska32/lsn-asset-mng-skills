# IMPL-B-FIX-01

Gemini B, R06–08/16, 기존파일소유와격리초안조건유지. 기준SHA실행머리말. file read/write만, tests는총괄실행. handoffs/IMPL-B-FIX-01.md만작성, 기존 IMPL-B인계의 '검증완료' 표는 '작성완료/미실행'으로정정. 실행안한테스트/공식스키마/live를검증했다고쓰지않는다.

실제23tests중FAIL1/ERROR1: workspace/runs/IMPL-B-check.tests.log. Naver nested stockExchangeType.delayTime=0를반영못하여None. 명시root/nested값만사용하고누락/invalid를0으로대체금지. pivotfixture bar2 open18>high16로계약거부되므로 합법OHLC이면서의도한pivot을검증하는fixture로수정.

총괄이실제사본에직접재현한P1:
1. naver_basic itemCode005930에 instrument_id='KRX:000660'을넘기면 is_usableTrue이며다른종목가격으로표시됨. 요청identity와sourceidentity가명확히일치해야함. 누락payloadidentity를caller로채우지않는다. 거래소/통화도같은규칙. unknownnation만으로currency를발명금지.
2. localTradedAt을제거해도retrieved.date로공개날짜를발명하고 is_usableTrue. 누락시timeUNKNOWN/ineligible여야하며수집시각을거래시각으로대체금지. Kraken ticker도retrieved를actualmarkettime으로표시함. raw보존과계산적격성을구분, missing/future/invalid/sourcezone/timeorder는ineligible. regularclose를aftermarket의time으로fresh표시하지말고각가격의정확한session/timestamp를확인못하면unknown. 명시delay없으면unknown. 시간외 quote와regularclose는섞지않는다.
3. 실제 naver_ohlcv 공개사본은split/adjustment/calendar/완료receipt가없는데 parser가 SPLIT_ADJUSTED로발명하고110bars is_usableTrue. unknownmetadata는rawcollection으로보존하되validatedBarSet/technical입력으로승격금지. source-backed adjustment/calendar/completion receipt를명시인자로받아확인할수있을때만분석가능. 공통DTO변경필요시A요청인계, 자기소유typedresult에미검증상태표현가능. bare BarSet을technical함수에넘기는우회도validatedinput경계필요. gap/duplicate/out-of-order/invalid바를삭제한뒤rollingwindow가연속인척분석하지않는다. sourcecoverage/cutoff를검증한contiguous구간만소비하고raw실패이유보존.

source-checks문서와실제source-inputs사용을우선. Yahoo chart와Coinbase ticker는총괄live200+사본확보된대체경로이므로구체adapter추가해서연결. Investing는실제403/원문미확인인데임의공통JSON을실제웹파서로문서화하지않는다. 실측endpoint/source-schema없는경로는unsupported/fixture-only. Kraken추가가필요하면실제필요endpoint와schema확인요청, 현재사본으로확인한것처럼쓰지않는다. JSON parse_float=Decimal/nonfinite/bool거부로정밀도보존(공통Ahttp뒤통합). sourceplan/fallback이실제provider parse실패/부적격후다음source로이동하도록API인계.

독립 손계산/접두사불변은유지하며위부정+정상metadatafixture추가. 사실상모든결과unsupported로만만들지말고명시검증정보가있는정상경로는시세/지표계산성공. 인계에실측/미실행구분과본소유API/공통연결요구를정확히기록.
