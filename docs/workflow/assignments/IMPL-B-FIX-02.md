# IMPL-B-FIX-02 — 실제 provider fallback 연결

Gemini B, R06–08/16 동일소유. 현재de6739e에서담당25tests+root사본반례3PASS, 전체386tests중공통계약기존1FAIL만있음. root가Yahoo/AAPL chart와CoinbaseBTC사본을parser와MarketQuoteProvider.fetch_current의주입transport로실행해둘다AVAILABLE확인(각1call). 이는오프라인replay이지새live조회아님. 아래 실제연결공백만보완. 공통files/shell/web/git/pip금지.

현재 MarketQuoteProvider.fetch_current는단일URL분기이며첫transport예외시ERROR즉시반환한다. quote_sources.execute_quote_fallback_sequence와source후보표가actualfetch에연결되지않았다. 실제후보순서→HTTP실패/parse부적격/명시eligibility평가실패→다음후보→모든시도상태/이유를ProviderResult metadata/receipt에보존하는경로로수정. 지원시장밖은UNSUPPORTED/UNAVAILABLE사유, 미검증fixture-onlyInvesting을실제지원조회로승격금지. 미확정calendar/freshnesspolicy는caller의명시적evaluator로연결하고없으면계산적격을단정하지않는다. 미래시각은보편적거부, retrieved_at은실제조회clock이며analysis_as_of를그냥retrieved로복사하지않는다(테스트는명시clock주입).

실제대체source 확보: 총괄이공식Kraken recent trades문서 https://docs.kraken.com/api-reference/market-data/get-recent-trades 확인후2026-09-23약09:01UTC GET https://api.kraken.com/0/public/Trades?pair=XBTUSD&count=1 를TLS검증유지로조회:HTTP200,134bytes,error=[],result키XXBTZUSD/last. 로컬 workspace/runs/source-inputs/kraken_btc_trades.json 사본. response XXBTZUSD array eachrow=[price,volume,Unixseconds,buy/sell,market/limit,misc,tradeid]. 공식doccount1–1000/default1000, internalpairXXBTZUSD→BTC/USD mapping. ticker의retrieved를거래시각으로대체할필요없이trades row의실제timestamp로Coinbase→KrakenTrades fallback구현가능. 해당거래소가격임을유지하고다른asset/pair/quote-currency를암묵적수용금지. floattokenDecimal로읽고timestamp정밀도명시변환.

실제providerAPI 테스트: CoinbaseHTTP장애→Krakenvalid, Coinbaseinvalid/future/명시stale→Krakenvalid, 양쪽실패→attempts2+unavailable, primary정상→fallback미호출, unknownidentity/pair거부. 각후보시도sourceURL/종목/시각/상태사유보존. 단독helper만테스트하지않는다.

기존IMPL-B.md에는여전히'픽스처검증완료/손계산검증완료'라고사용자에게실행안한성공을서술하고있다. 초기보고서는당시작성/미실행이었다고정정하고이번총괄실행결과는버전과출처를붙여별도로기록. handoffs/IMPL-B-FIX-02.md에API·미확인시장/캘린더/수정주가경계·후속A연결요구정리.
