"""Render a static dashboard from persisted run.db results; no browser-side finance calculations."""

from __future__ import annotations

import html
import json
import sqlite3
import sys
from pathlib import Path


LABELS = {
    "FANUC": "FANUC", "MITSUBISHI_HEAVY": "미쓰비시중공업", "HANWHA_OCEAN": "한화오션",
    "SAMSUNG_HEAVY": "삼성중공업", "HMM": "HMM", "HYUNDAI_MOVEX": "현대무벡스",
    "KOREAN_AIR": "대한항공", "POSCO_DX": "포스코DX", "JPY": "JPY", "KRW": "KRW", "USD": "USD",
    "JAPAN": "일본 주식", "KOREA": "한국 주식", "FACTORY_AUTOMATION": "공장자동화/로봇",
    "SHIPBUILDING_DEFENSE": "조선/방산", "SHIPPING": "해운", "LOGISTICS_AUTOMATION": "물류자동화",
    "AIRLINE": "항공", "INDUSTRIAL_DIGITALIZATION": "산업 디지털화", "CASH_COMPONENTS": "외화 현금 구성요소",
    "JAPAN_EQUITY": "일본 주식", "AUTOMATION": "자동화 테마",
}


def won(value: object) -> str:
    return f"{round(float(value)):,}원"


def bar_rows(items: list[tuple[str, float]], *, signed: bool = False, unit: str = "원") -> str:
    scale = max((abs(value) for _, value in items), default=1.0) or 1.0
    rows: list[str] = []
    for key, value in items:
        width = max(2.0, abs(value) / scale * 100)
        css = "negative" if signed and value < 0 else "positive" if signed else "neutral"
        shown = f"{value:+.2f}%" if unit == "%" else won(value)
        rows.append(
            f'<div class="bar-row" title="{html.escape(LABELS.get(key, key))}: {html.escape(shown)}">'
            f'<div class="bar-label">{html.escape(LABELS.get(key, key))}</div>'
            f'<div class="bar-track"><span class="bar-fill {css}" style="width:{width:.2f}%"></span></div>'
            f'<div class="bar-value">{html.escape(shown)}</div></div>'
        )
    return "".join(rows)


def render(run_db: Path) -> Path:
    uri = f"file:{run_db.resolve().as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    metadata = dict(connection.execute("SELECT * FROM run_metadata").fetchone())
    pinned = dict(connection.execute("SELECT * FROM pinned_personal_state").fetchone())
    component_row = connection.execute(
        "SELECT result_json FROM calculations WHERE calculation_name='confirmed_components_and_absolute_scenarios'"
    ).fetchone()
    reconciliation_row = connection.execute(
        "SELECT result_json FROM calculations WHERE calculation_name='portfolio_total_reconciliation'"
    ).fetchone()
    if component_row is None or reconciliation_row is None:
        raise RuntimeError("required persisted dashboard calculations are missing")
    data = json.loads(component_row[0])
    reconciliation = json.loads(reconciliation_row[0])
    materiality = [dict(row) for row in connection.execute("SELECT * FROM materiality_decisions ORDER BY rowid")]
    review = [dict(row) for row in connection.execute("SELECT * FROM review_findings ORDER BY rowid")]
    evidence = [dict(row) for row in connection.execute("SELECT * FROM evidence ORDER BY rowid")]
    tasks = [dict(row) for row in connection.execute("SELECT * FROM task_states ORDER BY rowid")]
    connection.close()

    holdings = data["holdings"]
    holding_rows = [(row["instrument_id"], float(row["value_krw"])) for row in holdings]
    currency_rows = [(key, float(value)) for key, value in data["currency_exposure_krw"].items()]
    country_rows = [(key, float(value)) for key, value in data["country_equity_exposure_krw"].items()]
    sector_rows = [(key, float(value)) for key, value in data["exclusive_sector_exposure_krw"].items()]
    concentration_rows = [(key, float(value)) for key, value in data["concentration_exposure_krw"].items()]
    pnl_rows = [(row["instrument_id"], float(row["pnl_rate_percent"])) for row in holdings]
    scenario_rows = [(row["name"], float(row["impact_krw"])) for row in data["scenarios"]]

    materiality_rows = "".join(
        "<tr>"
        f"<td>{html.escape(LABELS.get(row['subject'], row['subject']))}</td>"
        "<td>PARTIAL</td>"
        f"<td><span class='status'>{html.escape(row['decision'])}</span></td>"
        f"<td>{html.escape(row['rationale'])}</td>"
        f"<td>{'요청됨' if row['decision'] == 'AUTO_PASS_USER_SPECIFIED' else '근거 부족'}</td>"
        "</tr>"
        for row in materiality
    )
    scenario_table = "".join(
        f"<tr><td>{html.escape(row['name'])}</td><td>{won(row['impact_krw'])}</td>"
        f"<td>PARTIAL</td><td>{html.escape(LABELS.get(row['largest_contributor'], row['largest_contributor']))}</td></tr>"
        for row in data["scenarios"]
    )
    evidence_rows = "".join(
        f"<tr><td><code>{html.escape(row['evidence_id'])}</code></td>"
        f"<td>{html.escape(row['evidence_type'])}</td><td>{html.escape(row['observed_at'] or 'UNKNOWN')}</td>"
        f"<td><span class='status warn'>{html.escape(row['freshness_status'] or 'UNKNOWN')}</span></td></tr>"
        for row in evidence
    )
    task_rows = "".join(
        f"<li><span>{html.escape(row['task_name'])}</span><strong>{html.escape(row['task_status'])}</strong></li>"
        for row in tasks
    )
    review_rows = "".join(f"<li>{html.escape(row['finding_text'])}</li>" for row in review)

    document = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>검증된 포트폴리오 대시보드</title>
<style>
:root{{--bg:#07111f;--panel:#101d2d;--panel2:#142438;--text:#eef5ff;--muted:#9fb0c5;--line:#26384e;--blue:#5aa7ff;--green:#4ed6a2;--red:#ff7185;--amber:#ffc857}}
*{{box-sizing:border-box}} body{{margin:0;background:linear-gradient(140deg,#06101d,#0b1929);color:var(--text);font-family:Inter,"Noto Sans KR",system-ui,sans-serif;line-height:1.5}}
main{{max-width:1180px;margin:auto;padding:28px 20px 60px}} h1{{font-size:30px;margin:0 0 4px}} h2{{font-size:19px;margin:0 0 16px}} h3{{font-size:15px;margin:0 0 12px;color:var(--muted)}} p{{margin:0}} .muted{{color:var(--muted)}}
.header{{display:flex;justify-content:space-between;gap:20px;align-items:flex-end;margin-bottom:22px}} .status{{display:inline-block;padding:3px 9px;border-radius:999px;background:#243956;color:#cfe4ff;font-size:12px}} .status.warn{{background:#493b1c;color:#ffe29a}}
.grid{{display:grid;grid-template-columns:repeat(12,1fr);gap:14px}} .card{{background:linear-gradient(180deg,var(--panel2),var(--panel));border:1px solid var(--line);border-radius:16px;padding:17px;box-shadow:0 14px 35px rgba(0,0,0,.16)}}
.metric{{grid-column:span 3;min-height:112px}} .metric .label{{color:var(--muted);font-size:13px}} .metric .value{{font-size:23px;font-weight:700;margin-top:9px}} .metric .note{{font-size:12px;color:var(--muted);margin-top:5px}} .span6{{grid-column:span 6}} .span12{{grid-column:span 12}} .span4{{grid-column:span 4}}
.bar-row{{display:grid;grid-template-columns:145px 1fr 105px;gap:10px;align-items:center;margin:9px 0;font-size:13px}} .bar-track{{height:10px;background:#223247;border-radius:8px;overflow:hidden}} .bar-fill{{display:block;height:100%;border-radius:8px;background:var(--blue)}} .bar-fill.positive{{background:var(--green)}} .bar-fill.negative{{background:var(--red)}} .bar-value{{text-align:right;font-variant-numeric:tabular-nums}} .bar-label{{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
table{{width:100%;border-collapse:collapse;font-size:13px}} th,td{{padding:10px 8px;text-align:left;border-bottom:1px solid var(--line);vertical-align:top}} th{{color:var(--muted);font-weight:600}} code{{color:#b9d8ff}} ul{{padding-left:18px;margin:0}} li{{margin:7px 0}} .pipeline{{list-style:none;padding:0}} .pipeline li{{display:flex;justify-content:space-between;border-bottom:1px solid var(--line);padding:8px 0}}
.risk-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}} .risk-item{{background:#0c1826;border:1px solid var(--line);border-radius:12px;padding:13px}} .risk-item strong{{display:block;margin-top:6px}} .critical{{color:var(--red)}} .partial{{color:var(--amber)}}
@media(max-width:850px){{.metric{{grid-column:span 6}}.span6,.span4{{grid-column:span 12}}.risk-grid{{grid-template-columns:1fr 1fr}}}}
@media(max-width:520px){{main{{padding:18px 12px 40px}}.header{{display:block}}.metric{{grid-column:span 12}}.bar-row{{grid-template-columns:100px 1fr 88px}}.risk-grid{{grid-template-columns:1fr}}h1{{font-size:24px}}}}
</style></head><body><main>
<header class="header"><div><h1>Portfolio Runtime Dashboard</h1><p class="muted">검증 run · {html.escape(metadata['run_id'])}</p></div><div><span class="status warn">PARTIAL · LOW CONFIDENCE</span></div></header>
<section class="grid">
<article class="card metric"><div class="label">Portfolio Total</div><div class="value critical">UNRESOLVED</div><div class="note">표시 총자산 {won(1046450)} · 확정 분모 아님</div></article>
<article class="card metric"><div class="label">Stock Value</div><div class="value">{won(data['stock_group_total_krw'])}</div><div class="note">증권사 그룹 총계 관측값</div></article>
<article class="card metric"><div class="label">Cash</div><div class="value">{won(data['cash_group_total_krw'])}</div><div class="note">예수금 그룹 총계 관측값</div></article>
<article class="card metric"><div class="label">Holdings</div><div class="value">{len(holdings)}개</div><div class="note">주식 종목 수</div></article>
<article class="card metric"><div class="label">JPY Exposure</div><div class="value">{won(data['currency_exposure_krw']['JPY'])}</div><div class="note">일본 주식 + JPY 현금 · PARTIAL</div></article>
<article class="card metric"><div class="label">USD Exposure</div><div class="value">{won(data['currency_exposure_krw']['USD'])}</div><div class="note">USD 현금 구성요소 · PARTIAL</div></article>
<article class="card metric"><div class="label">KRW Exposure</div><div class="value">{won(data['currency_exposure_krw']['KRW'])}</div><div class="note">한국 주식 구성요소 · PARTIAL</div></article>
<article class="card metric"><div class="label">Analysis As Of</div><div class="value">09:42 KST</div><div class="note">2026-08-14 · 고정됨</div></article>

<article class="card span6"><h2>Holdings Allocation</h2><p class="muted">확인된 구성요소 평가액 · 총자산 비중 아님</p>{bar_rows(holding_rows)}</article>
<article class="card span6"><h2>Currency Exposure · PARTIAL</h2><p class="muted">확인된 절대 노출액</p>{bar_rows(currency_rows)}</article>
<article class="card span6"><h2>Country Equity Exposure</h2>{bar_rows(country_rows)}</article>
<article class="card span6"><h2>Sector Classification</h2><p class="muted">상호배타적 직접 분류. 외화 현금은 구성요소 관측값.</p>{bar_rows(sector_rows)}</article>
<article class="card span6"><h2>Concentration</h2><p class="muted">테마는 중복될 수 있으며 절대 노출로 표시</p>{bar_rows(concentration_rows)}</article>
<article class="card span6"><h2>Profit / Loss</h2><p class="muted">스크린샷 수익률이며 매수·매도 신호가 아님</p>{bar_rows(pnl_rows, signed=True, unit='%')}</article>
<article class="card span12"><h2>Scenario Impact</h2><p class="muted">절대 KRW 영향만 authoritative. Impact %는 reconciliation 미해결로 PARTIAL.</p>{bar_rows(scenario_rows, signed=True)}<table><thead><tr><th>Scenario</th><th>Impact</th><th>Impact %</th><th>Largest contributor</th></tr></thead><tbody>{scenario_table}</tbody></table></article>

<article class="card span12"><h2>Risk Dashboard</h2><div class="risk-grid">
<div class="risk-item">Concentration<strong class="partial">PARTIAL</strong></div><div class="risk-item">Currency Exposure<strong class="partial">PARTIAL</strong></div><div class="risk-item">Country Exposure<strong class="partial">PARTIAL</strong></div>
<div class="risk-item">Sector / Theme<strong>AVAILABLE (absolute)</strong></div><div class="risk-item">Volatility<strong>UNAVAILABLE</strong></div><div class="risk-item">Maximum Drawdown<strong>UNAVAILABLE</strong></div>
<div class="risk-item">Correlation<strong>UNAVAILABLE</strong></div><div class="risk-item">Liquidity<strong>PARTIAL</strong></div><div class="risk-item">Data Quality<strong class="critical">RECONCILIATION UNRESOLVED</strong></div>
<div class="risk-item">Market Price Freshness<strong class="partial">PARTIAL</strong></div><div class="risk-item">Valuation<strong>UNAVAILABLE</strong></div><div class="risk-item">Financial Data<strong>UNAVAILABLE IN RUN</strong></div>
</div></article>

<article class="card span12"><h2>Materiality Gate</h2><table><thead><tr><th>Asset</th><th>Weight</th><th>Gate</th><th>Reason</th><th>Deep Research</th></tr></thead><tbody>{materiality_rows}</tbody></table></article>
<article class="card span6"><h2>Fixed Pipeline</h2><ul class="pipeline">{task_rows}</ul></article>
<article class="card span6"><h2>Conditional Review</h2><ul>{review_rows}</ul></article>
<article class="card span12"><h2>Valuation</h2><p class="critical">VALUATION DATA UNAVAILABLE</p><p class="muted">권위가격과 일관된 valuation evidence가 run.db에 없어 범위를 생성하지 않았습니다.</p></article>
<article class="card span6"><h2>Top 3 Risks</h2><ol><li>Portfolio reconciliation unresolved</li><li>JPY·일본 주식 절대 노출 집중</li><li>FANUC·자동화 및 조선/방산 테마 중복</li></ol></article>
<article class="card span6"><h2>Top 3 Actions To Consider</h2><ol><li>증권사 총자산·예수금 포함관계 확인</li><li>비중 판단 전 authoritative denominator 확정</li><li>시장·재무 evidence를 수집한 뒤 thesis review</li></ol></article>
<article class="card span12"><h2>Data As Of / Evidence</h2><p class="muted">Analysis: {html.escape(metadata['analysis_as_of'])} · Portfolio: {html.escape(pinned['portfolio_data_as_of'])} · Market/Financial/FX/News: UNAVAILABLE 또는 PARTIAL</p><table><thead><tr><th>Evidence ID</th><th>Type</th><th>Observed At</th><th>Freshness</th></tr></thead><tbody>{evidence_rows}</tbody></table></article>
<article class="card span12"><h2>Reconciliation</h2><p><strong class="critical">{html.escape(reconciliation['status'])}</strong></p><p class="muted">Confirmed group total {won(reconciliation['confirmed_group_total'])} · Naive component total {won(reconciliation['naive_component_total'])} · Reported difference {won(reconciliation['reported_difference'])}. Naive total은 분모로 사용되지 않았습니다.</p></article>
</section></main></body></html>"""
    report_dir = run_db.parent / "report"
    report_dir.mkdir(parents=True, exist_ok=True)
    output = report_dir / "index.html"
    output.write_text(document, encoding="utf-8")
    data_dir = report_dir / "data"
    data_dir.mkdir(exist_ok=True)
    (data_dir / "dashboard.json").write_text(
        json.dumps(
            {"run_metadata": metadata, "pinned_state": pinned, "reconciliation": reconciliation, "dashboard": data,
             "materiality": materiality, "review": review},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    print(output)
    return output


if __name__ == "__main__":
    render(Path(sys.argv[1]))
