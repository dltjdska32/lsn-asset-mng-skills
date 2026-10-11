from dataclasses import dataclass
from typing import Mapping, Sequence

@dataclass
class TerminalScenarioInput:
    horizon_years: int
    revenue_growth_cagr: float
    terminal_multiple: float
    terminal_multiple_metric: str  # e.g. "revenue", "operating_income", "fcf"
    multiple_target: str # "enterprise" or "equity"
    current_revenue: float
    terminal_net_debt: float
    fully_diluted_shares: float
    source_refs: Sequence[str]
    operating_margin: float | None = None
    fcf_margin: float | None = None
    fcf_basis: str | None = None
    roic: float | None = None
    wacc: float | None = None

@dataclass
class TerminalScenarioResult:
    terminal_value_enterprise: float | None
    terminal_value_equity: float
    terminal_value_per_share: float
    formulas: Mapping[str, str]
    source_refs: Sequence[str]
    notes: str = "Arithmetic projection only; not an approved investment forecast."

def calculate_terminal_scenario(inputs: TerminalScenarioInput) -> TerminalScenarioResult:
    import math
    def check_float(val, name):
        if val is not None:
            if isinstance(val, bool) or not isinstance(val, (int, float)) or math.isnan(val) or math.isinf(val):
                raise ValueError(f"{name} must be a finite number")
    
    check_float(inputs.revenue_growth_cagr, "revenue_growth_cagr")
    check_float(inputs.terminal_multiple, "terminal_multiple")
    check_float(inputs.current_revenue, "current_revenue")
    check_float(inputs.terminal_net_debt, "terminal_net_debt")
    check_float(inputs.fully_diluted_shares, "fully_diluted_shares")
    check_float(inputs.operating_margin, "operating_margin")
    check_float(inputs.fcf_margin, "fcf_margin")
    check_float(inputs.roic, "roic")
    check_float(inputs.wacc, "wacc")
    
    if isinstance(inputs.horizon_years, bool) or not isinstance(inputs.horizon_years, int) or inputs.horizon_years <= 0:
        raise ValueError("horizon_years must be a positive integer")
    if inputs.current_revenue <= 0 or inputs.fully_diluted_shares <= 0:
        raise ValueError("Invalid positive inputs required for revenue and shares")
    if inputs.multiple_target not in {"enterprise", "equity"}:
        raise ValueError("multiple_target must be 'enterprise' or 'equity'")
    if not inputs.source_refs:
        raise ValueError("source_refs required for formula")
        
    if inputs.revenue_growth_cagr <= -1:
        raise ValueError("revenue_growth_cagr must be > -1")
    if inputs.terminal_multiple <= 0:
        raise ValueError("terminal_multiple must be a finite positive number")
        
    notes = "Arithmetic projection only; not an approved investment forecast."
    if inputs.roic is not None and inputs.wacc is not None:
        if inputs.revenue_growth_cagr > 0 and inputs.roic < inputs.wacc:
            notes += " WARNING: Growing with negative economic spread (ROIC < WACC)."
    else:
        notes += " Reinvestment economics not validated (missing ROIC or WACC inputs)."
    
    terminal_revenue = inputs.current_revenue * ((1 + inputs.revenue_growth_cagr) ** inputs.horizon_years)
    
    formulas = {
        "terminal_revenue": f"current_revenue * (1 + {inputs.revenue_growth_cagr})^{inputs.horizon_years}"
    }

    if inputs.terminal_multiple_metric == "revenue":
        metric_value = terminal_revenue
    elif inputs.terminal_multiple_metric == "operating_income":
        if inputs.operating_margin is None:
            raise ValueError("operating_margin required for operating_income multiple")
        metric_value = terminal_revenue * inputs.operating_margin
        formulas["metric_value"] = f"terminal_revenue * {inputs.operating_margin}"
    elif inputs.terminal_multiple_metric == "fcf":
        if inputs.fcf_basis not in {"fcff", "fcfe"}:
            raise ValueError("Explicit fcf_basis ('fcff' or 'fcfe') required for generic fcf")
        if inputs.fcf_basis == "fcff" and inputs.multiple_target != "enterprise":
            raise ValueError("FCFF requires enterprise multiple_target")
        if inputs.fcf_basis == "fcfe" and inputs.multiple_target != "equity":
            raise ValueError("FCFE requires equity multiple_target")
        if inputs.fcf_margin is None:
            raise ValueError("fcf_margin required for fcf multiple")
        metric_value = terminal_revenue * inputs.fcf_margin
        formulas["metric_value"] = f"terminal_revenue * {inputs.fcf_margin}"
    else:
        raise ValueError(f"Unsupported multiple metric: {inputs.terminal_multiple_metric}")

    base_value = metric_value * inputs.terminal_multiple
    
    if inputs.multiple_target == "enterprise":
        tv_ent = base_value
        formulas["terminal_value_enterprise"] = f"metric_value * {inputs.terminal_multiple}"
        tv_eq = tv_ent - inputs.terminal_net_debt
        formulas["terminal_value_equity"] = f"terminal_value_enterprise - ({inputs.terminal_net_debt})"
    else:
        tv_ent = None
        tv_eq = base_value
        formulas["terminal_value_equity"] = f"metric_value * {inputs.terminal_multiple}"
    
    if tv_eq <= 0:
        raise ValueError("insolvency/noninvestable scenario: negative equity")

    tv_ps = tv_eq / inputs.fully_diluted_shares
    formulas["terminal_value_per_share"] = f"terminal_value_equity / {inputs.fully_diluted_shares}"

    if math.isinf(tv_eq) or math.isnan(tv_eq) or math.isinf(tv_ps) or math.isnan(tv_ps):
        raise ValueError("output overflow")

    return TerminalScenarioResult(
        terminal_value_enterprise=tv_ent,
        terminal_value_equity=tv_eq,
        terminal_value_per_share=tv_ps,
        formulas=formulas,
        source_refs=inputs.source_refs,
        notes=notes
    )
