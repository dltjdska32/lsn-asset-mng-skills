"""Pure evidence-linked capital priorities; concentration never instructs a sale."""
from dataclasses import dataclass, field
from decimal import Decimal, localcontext
from enum import StrEnum
from typing import Mapping


DIMENSIONS = ('growth', 'valuation', 'business_quality', 'financial_quality', 'industry_growth', 'risk_downside')
DEFAULT_WEIGHTS = dict(zip(DIMENSIONS, (Decimal('.30'), Decimal('.25'), Decimal('.15'), Decimal('.10'), Decimal('.10'), Decimal('.10'))))


class CapitalCategory(StrEnum):
    CORE_CONCENTRATION = 'CORE_CONCENTRATION'
    SECONDARY_GROWTH = 'SECONDARY_GROWTH'
    HOLD = 'HOLD'
    WATCH = 'WATCH'
    REDUCE = 'REDUCE'
    EXIT_CANDIDATE = 'EXIT_CANDIDATE'


CATEGORY_LABELS = dict(zip(CapitalCategory, ('핵심 집중', '보조 성장', '보유', '관찰', '비중 축소', '정리 후보')))


@dataclass(frozen=True)
class CapitalScenario:
    name: str
    earnings_per_share: Decimal
    earnings_growth: Decimal
    annual_dilution: Decimal
    terminal_multiple: Decimal
    dividends_per_share: Decimal
    evidence_bindings: Mapping[str, str]


@dataclass(frozen=True)
class CapitalCandidate:
    instrument_id: str
    held: bool = True
    weight: Decimal | None = None
    scores: Mapping[str, Decimal] = field(default_factory=dict)
    score_evidence: Mapping[str, str] = field(default_factory=dict)
    scenarios: tuple[CapitalScenario, ...] = ()
    price: Decimal | None = None
    price_evidence_id: str | None = None
    verified_price: bool = False
    expansion_planned: bool | None = None
    optionality_intent: str | None = None
    thematic: bool = False
    geopolitical_high: bool = False
    thesis_broken: bool = False
    thesis_breakers: tuple[str, ...] = ()
    material_events: tuple[str, ...] = ()
    allocation_proposed: bool = False


@dataclass(frozen=True)
class CompetitionPolicy:
    weights: Mapping[str, Decimal] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    core_min_score: Decimal = Decimal('.80')
    secondary_min_score: Decimal = Decimal('.65')
    hold_min_score: Decimal = Decimal('.40')
    exit_max_score: Decimal = Decimal('.20')
    very_high_cagr: Decimal = Decimal('.25')

    def __post_init__(self):
        if set(self.weights) != set(DIMENSIONS):
            raise ValueError('all six score dimensions required')
        for v in self.weights.values():
            _finite(v)
            if v < 0:
                raise ValueError('negative score weight')
        if sum(self.weights.values()) != 1:
            raise ValueError('score weights must sum to one')
        for v in (self.core_min_score, self.secondary_min_score, self.hold_min_score, self.exit_max_score, self.very_high_cagr):
            _finite(v)
        if not 0 <= self.exit_max_score < self.hold_min_score < self.secondary_min_score < self.core_min_score <= 1 or self.very_high_cagr <= 0:
            raise ValueError('invalid category thresholds')


@dataclass(frozen=True)
class CompetitionRow:
    instrument_id: str
    held: bool
    category: CapitalCategory
    score: Decimal | None
    scenario_cagrs: Mapping[str, Decimal]
    weight: Decimal | None
    flags: tuple[str, ...]
    missing_inputs: tuple[str, ...]
    review_triggers: tuple[str, ...]
    automatic_reduce: bool = False


@dataclass(frozen=True)
class RotationCandidate:
    from_instrument: str
    to_instrument: str
    status: str
    net_destination_cagr: Decimal | None
    reason: str


@dataclass(frozen=True)
class CompetitionResult:
    ranked: tuple[CompetitionRow, ...]
    unranked: tuple[CompetitionRow, ...]
    rotations: tuple[RotationCandidate, ...]
    review_triggers: tuple[str, ...]
    weights: Mapping[str, Decimal]


def _finite(value):
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError('finite Decimal input required')


def scenario_cagrs(candidate):
    if not candidate.verified_price or not candidate.price_evidence_id or candidate.price is None:
        return {}, ('validated_price',)
    _finite(candidate.price)
    if candidate.price <= 0:
        raise ValueError('positive scenario price required')
    scenarios = candidate.scenarios
    if len(scenarios) != 3 or {s.name.lower() for s in scenarios} != {'bear', 'base', 'bull'}:
        return {}, ('explicit_bear_base_bull',)
    fields = {'earnings_per_share', 'earnings_growth', 'annual_dilution', 'terminal_multiple', 'dividends_per_share'}
    result = {}
    for s in scenarios:
        if set(s.evidence_bindings) != fields or any(not isinstance(v, str) or not v.strip() for v in s.evidence_bindings.values()):
            return {}, ('scenario_assumption_evidence',)
        for key in fields:
            _finite(getattr(s, key))
        if s.earnings_per_share <= 0 or s.earnings_growth <= -1 or s.annual_dilution < 0 or s.terminal_multiple <= 0 or s.dividends_per_share < 0:
            raise ValueError('unsupported scenario assumptions')
        with localcontext() as ctx:
            ctx.prec = 34
            future_eps = s.earnings_per_share * ((1 + s.earnings_growth) / (1 + s.annual_dilution)) ** 5
            result[s.name.lower()] = ((future_eps * s.terminal_multiple + s.dividends_per_share) / candidate.price) ** (Decimal(1) / 5) - 1
    if not result['bear'] <= result['base'] <= result['bull']:
        raise ValueError('Bear/Base/Bull outcomes must be ordered')
    return result, ()


def analyze_capital_competition(candidates, *, policy=None, rotation_friction=None):
    """Scores are research/allocation priorities, never expected return estimates.

    rotation_friction maps (seller, buyer) to an evidenced all-in upfront fraction.
    Omitted tax/fees/FX/slippage prevents a net-benefit conclusion.
    """
    policy = policy or CompetitionPolicy()
    if len({c.instrument_id for c in candidates}) != len(candidates):
        raise ValueError('duplicate capital candidate')
    rows = []
    triggers = []
    for c in candidates:
        if not c.instrument_id:
            raise ValueError('instrument identity required')
        if c.weight is not None:
            _finite(c.weight)
            if not 0 <= c.weight <= 1:
                raise ValueError('position weight must be a fraction')
        cagrs, missing = scenario_cagrs(c)
        missing = list(missing)
        for key in DIMENSIONS:
            if key not in c.scores or not c.score_evidence.get(key):
                missing.append('score:' + key)
            elif not isinstance(c.score_evidence[key], str):
                raise ValueError('score evidence ID required')
            else:
                _finite(c.scores[key])
                if not 0 <= c.scores[key] <= 1:
                    raise ValueError('scores must be normalized fractions')
        score = None if missing else sum((policy.weights[k] * c.scores[k] for k in DIMENSIONS), Decimal(0))
        category = CapitalCategory.WATCH
        if score is not None:
            if c.thesis_broken and score <= policy.exit_max_score:
                category = CapitalCategory.EXIT_CANDIDATE
            elif score < policy.hold_min_score:
                category = CapitalCategory.REDUCE
            elif score >= policy.core_min_score and c.scores['valuation'] >= Decimal('.6') and c.scores['business_quality'] >= Decimal('.6') and c.scores['risk_downside'] >= Decimal('.5') and cagrs['base'] > 0:
                category = CapitalCategory.CORE_CONCENTRATION
            elif score >= policy.secondary_min_score and c.scores['valuation'] >= Decimal('.5') and cagrs['base'] > 0:
                category = CapitalCategory.SECONDARY_GROWTH
            else:
                category = CapitalCategory.HOLD
        flags, local_triggers = [], []
        if c.weight is not None and c.weight > Decimal('.25'):
            flags.append('CONCENTRATION_RISK')
            local_triggers.append('SINGLE_ASSET_OVER_25_PERCENT')
        if c.weight is not None and c.weight > Decimal('.30'):
            local_triggers.append('SINGLE_ASSET_OVER_30_PERCENT')
        if c.held and c.weight is not None and c.weight <= Decimal('.01') and c.expansion_planned is False and not c.optionality_intent:
            flags.append('POSITION_TOO_SMALL_TO_MATTER')
        if any(v > policy.very_high_cagr for v in cagrs.values()):
            local_triggers.append('VERY_HIGH_EXPECTED_CAGR')
        if c.thematic:
            local_triggers.append('HIGH_GROWTH_THEMATIC')
        if c.geopolitical_high:
            local_triggers.append('HIGH_GEOPOLITICAL_RISK')
        if c.allocation_proposed:
            local_triggers.append('NEW_CAPITAL_CONCENTRATION_PROPOSAL')
        triggers.extend(local_triggers)
        rows.append(CompetitionRow(c.instrument_id, c.held, category, score, cagrs, c.weight, tuple(flags), tuple(missing), tuple(local_triggers)))
    held_weights = sorted((r.weight for r in rows if r.held and r.weight is not None), reverse=True)
    if sum(held_weights[:2], Decimal(0)) > Decimal('.50'):
        triggers.append('TOP_TWO_OVER_50_PERCENT')
    ranked = tuple(sorted((r for r in rows if r.score is not None), key=lambda r: (-r.score, r.instrument_id)))
    unranked = tuple(r for r in rows if r.score is None)
    rotations = []
    holdings = [r for r in ranked if r.held]
    if holdings:
        weakest = min(holdings, key=lambda r: (r.score, r.instrument_id))
        for target in ranked:
            if target.instrument_id == weakest.instrument_id or target.score <= weakest.score or target.scenario_cagrs['base'] <= weakest.scenario_cagrs['base']:
                continue
            friction = (rotation_friction or {}).get((weakest.instrument_id, target.instrument_id))
            net = None
            status, reason = 'FRICTIONS_UNAVAILABLE', '세금·수수료·FX·슬리피지 미확인; 재배치 순편익 확인 불가'
            if friction is not None:
                _finite(friction)
                if not 0 <= friction < 1:
                    raise ValueError('rotation friction must be a fraction below one')
                with localcontext() as ctx:
                    ctx.prec = 34
                    net = ((1 - friction) * (1 + target.scenario_cagrs['base']) ** 5) ** (Decimal(1) / 5) - 1
                status = 'REVIEW_CANDIDATE' if net > weakest.scenario_cagrs['base'] else 'NOT_JUSTIFIED'
                reason = '명시된 마찰비용 반영 시나리오 비교; 주문 지시 아님'
            rotations.append(RotationCandidate(weakest.instrument_id, target.instrument_id, status, net, reason))
    if rotations:
        triggers.append('CAPITAL_ROTATION_REVIEW')
    return CompetitionResult(ranked, unranked, tuple(rotations), tuple(dict.fromkeys(triggers)), dict(policy.weights))
