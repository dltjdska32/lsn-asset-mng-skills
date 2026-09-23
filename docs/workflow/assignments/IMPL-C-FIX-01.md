# IMPL-C-FIX-01

Gemini C, R12–13/16, 기존파일소유와격리초안조건유지. 기준SHA실행머리말. file read/write만. tests는총괄실행. handoffs/IMPL-C-FIX-01.md, 기존IMPL-C인계의'검증완료'는작성/정적읽기/실제미실행을구분하여정정.

workspace/runs/IMPL-C-check.tests.log 실제결과8개(13F테스트전체import실패포함)중1FAIL/1ERROR. test_r12_sec_13f.py233행 keywordarg `public_availability=filing_pre_pub := ...` syntaxerror. 정상Python구문으로수정하고다른생성자/enum/API도실제정의와대조. test_trade_gate_allows_formal_approval_only는feature.score_status='UNVALIDATED'라승인문자열만넣어도DISABLED가정상인데ENABLED기대하고있다. 테스트에맞춰게이트약화금지.

check_13f_trade_gate는현재caller가score_status와approval_ref문자열을바꾸면validation_ref='audit:r13_passed'를발명한다. 제거. 단순문자열/feature변조만으로가중치승인을생성하지않는다. 실제실행한 point-in-time/holdout/baseline/cost/coverage·leakage validation report와정책승인context가없으면disabled. 공통A가typedgate및신뢰된formula requirement를다음버전에제공예정이므로C는제공하는ValidationReport/검증registry입력연결API를명시하고임의승인논리를추가하지않는다. 여기서는성능검증자료가없으니UNVALIDATED상태가정상. 설명용features/보유변화는가능, 매매사용금지.

분기비교에서공시부재는매도라고단정금지. confidential뿐아니라coverage불명/보고manager/quarter/class/PRN·SH/putcall/split불일치도uncertain/incomparable. original/restatement/additions의중복·accession·공개cutoff와달력날짜보수cutoff를테스트. 신규테스트정상실행까지수정후인계. SECarchive403/rawXMLlive미확인그대로명시. syntheticXMLparser테스트를live확인으로쓰지않는다. 공통contracts코드는수정하지않는다.
