# IMPL-C-FIX-02

Gemini C, 기존소유/제약유지. 실행기준SHA머리말. 총괄실제21tests중1ERROR: workspace/runs/IMPL-C-FIX-01-check.tests.log. test_incomparability... fixture의 set_diff_mgr filingf3 안에 holding.filing_id=f2를넣어 contract단계에서막힘. dataclasses.replace 등으로유효한f3holding을만들어 manager불일치의 실제 비교거부를검증하라. 계약완화금지.

추가정적지적: providers/sec_13f.py parse_information_table_xml에서 filed_date없으면 report_period로schema연도를추정하고 완전unknown은scale1기본값. 보유분기≠신고schema시점, 과거분기정정은새양식일수있으므로 이추정제거. 검증된filingdate/sourcevintage mapping 또는 출처있는명시scale을사용하고날짜invalid/unknown/schema모호하면value_scale=None/raw값보존+가치비교unavailable. 원자료보존과eligible total분리, 누락행/missingCUSIP/value를조용히skip하고completecoverage를주장금지. 원문형식/필수행품질별파싱경고/coverage status를결과에보존하여비교기에전달한다. 정당한공시·신고액/수량경로는정상작동해야한다.

명시validationreport를받더라도 caller가score_status='VALIDATED'등문자열+approval_ref만바꿔매매ENABLE을발명하지않는다. 현재실증된backtest/holdout/cost/criteria없어UNVALIDATED가정상, 공통A의후속trustedgate context연결은인계. 실제모든validationchecks를합성report로단정하는테스트는피한다. 원문보고액은매입원가가아님/공시부재는실거래매도확정아님유지.

위sourcevintage부정/정상fixture와missingrow coverage전파test추가. handoffs/IMPL-C-FIX-02.md만인계. shell/git/pip/web/공통파일변경금지. 실행테스트통과주장금지.
