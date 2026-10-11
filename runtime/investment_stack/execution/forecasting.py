"""Post-valuation experimental price companion; no investment-decision authority.

Only same-run, selected provider source bodies re-parsed by the canonical OHLCV
parser may be used. Input JSON selects evidence *identifiers*, never price arrays.
Optional ML/framework imports occur only after this eligibility gate succeeds.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Callable
from uuid import uuid4
import hashlib
import json
import math
import sqlite3

from investment_stack.evidence.source_receipt import load_source_payload, verify_quote_body
from investment_stack.reporting.models import Availability, ReportSectionInput


def _aware(value: str | datetime) -> datetime:
    value = datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError('offset-aware timestamp required')
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class ForecastingConfig:
    chronos_model_dir: Path | None = None
    kronos_model_dir: Path | None = None
    kronos_tokenizer_dir: Path | None = None
    kronos_source_root: Path | None = None
    xgboost_artifact: Path | None = None
    lightgbm_artifact: Path | None = None
    terminal_projection_file: Path | None = None
    device: str = 'cpu'
    local_files_only: bool = True

    @classmethod
    def from_file(cls, path: Path) -> 'ForecastingConfig':
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            raise ValueError('forecast config must be object')
        supported = {'chronos_model_dir','kronos_model_dir','kronos_tokenizer_dir',
                     'kronos_source_root','xgboost_artifact','lightgbm_artifact','terminal_projection_file','device','local_files_only'}
        if set(data) - supported:
            raise ValueError('unknown forecast config keys')
        if data.get('local_files_only', True) is not True:
            raise ValueError('remote weights/inference are forbidden')
        if data.get('device', 'cpu') != 'cpu':
            raise ValueError('only explicitly local CPU inference is supported by this bridge')
        paths = {}
        for key in supported - {'device','local_files_only'}:
            val = data.get(key)
            if val is not None:
                if not isinstance(val, str) or not Path(val).is_absolute():
                    raise ValueError(key + ' requires an absolute local path')
                paths[key] = Path(val)
        if bool(paths.get('kronos_model_dir')) != bool(paths.get('kronos_tokenizer_dir')) or bool(paths.get('kronos_model_dir')) != bool(paths.get('kronos_source_root')):
            raise ValueError('Kronos model/tokenizer/pinned source must all be provided')
        return cls(**paths)

    def configured(self) -> bool:
        return bool(self.chronos_model_dir or self.kronos_model_dir or self.xgboost_artifact or self.lightgbm_artifact)


@dataclass(frozen=True)
class ForecastIntegrationResult:
    sections: tuple[ReportSectionInput, ...]
    calculation_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    missing_inputs: tuple[str, ...]
    per_instrument: Mapping[str, Mapping[str, Any]]
    review_triggers: tuple[str, ...] = ()


from contextlib import contextmanager
from threading import RLock
import os
_OFFLINE_ENV_LOCK = RLock()


@contextmanager
def _offline_inference_scope():
    """Serialise scoped HF offline environment without leaking process settings."""
    keys = ('HF_HUB_OFFLINE', 'TRANSFORMERS_OFFLINE')
    with _OFFLINE_ENV_LOCK:
        old = {k: os.environ.get(k) for k in keys}
        try:
            for k in keys: os.environ[k] = '1'
            yield
        finally:
            for k, previous in old.items():
                if previous is None: os.environ.pop(k, None)
                else: os.environ[k] = previous


def _selection_map(path: Path | None) -> Mapping[str, Mapping[str, str]]:
    if path is None:
        return {}
    raw = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(raw, dict):
        raise ValueError('forecast inputs must map instrument IDs to persisted evidence IDs')
    for iid, entry in raw.items():
        if not isinstance(iid, str) or not isinstance(entry, dict) or set(entry) != {'history_evidence_id','quote_evidence_id'}:
            raise ValueError('forecast inputs only support two source evidence IDs per instrument')
        if not all(isinstance(v, str) and v for v in entry.values()):
            raise ValueError('forecast evidence IDs must be non-empty strings')
    return raw


class PostValuationForecastService:
    def __init__(self, run, config: ForecastingConfig, *, input_selections: Mapping[str, Mapping[str, str]] | None = None,
                 engine_factory=None, source_collector=None):
        self.run = run
        self.config = config
        self.input_selections = dict(input_selections or {})
        self.engine_factory = engine_factory
        self.source_collector = source_collector

    def _source_input(self, iid: str, currency: str, cutoff: datetime):
        """Re-parse persisted selected provider bodies; caller-supplied arrays are never eligible."""
        from investment_stack.providers.ohlcv import parse_naver_ohlcv, parse_yahoo_chart_ohlcv
        from investment_stack.contracts.market import AdjustmentMode
        from investment_stack.evidence.source_receipt import payload_sha256
        from zoneinfo import ZoneInfo
        from calendar import monthrange
        import pandas as pd

        ids = self.input_selections.get(iid)
        if not isinstance(ids, Mapping) or set(ids) != {'history_evidence_id', 'quote_evidence_id'}:
            raise ValueError('selected provider history and quote evidence IDs missing')
        ctx = self.run.fetch_phase6_context()
        evidence = {e['evidence_id']: e for e in ctx['evidence'] if e['run_id'] == self.run.run_id}
        def accepted(eid):
            e = evidence.get(eid)
            if not e or e['instrument_id'] != iid or e.get('selection_state') != 'SELECTED':
                raise ValueError('cross-run/unselected/wrong-instrument evidence refused')
            if e.get('currency') and e['currency'] != currency:
                raise ValueError('evidence currency mismatch')
            if not all(e.get(t) for t in ('observed_at', 'published_at', 'retrieved_at')):
                raise ValueError('observed/published/retrieved PIT timestamps are required')
            observed, published, retrieved = (_aware(e[t]) for t in ('observed_at', 'published_at', 'retrieved_at'))
            if observed > cutoff or published > cutoff or retrieved < max(observed, published):
                raise ValueError('future observation/publication or retrieval-before-publication refused')
            if e.get('official_confirmation_status') not in ('CONFIRMED', 'OFFICIAL', 'VERIFIED'):
                raise ValueError('unverified or rumored source evidence refused')
            if e.get('freshness_status') not in ('FRESH', 'LAST_VALID_CLOSE'):
                raise ValueError('unknown, stale or rejected evidence freshness')
            return e
        hist_e = accepted(ids['history_evidence_id'])
        quote_e = accepted(ids['quote_evidence_id'])
        if quote_e.get('metric') != 'current_price' or not quote_e.get('value_text'):
            raise ValueError('selected eligible current_price quote required')
        qprice = Decimal(str(quote_e['value_text']))
        if not qprice.is_finite() or qprice <= 0:
            raise ValueError('quote price invalid')
        # The native quote is nominal. A split-adjusted history requires an
        # independently verified conversion; no implicit factor=1 assumption.
        qmeta = json.loads(quote_e.get('metadata_json') or '{}')
        hmeta = json.loads(hist_e.get('metadata_json') or '{}')
        if not isinstance(qmeta, dict) or not isinstance(hmeta, dict):
            raise ValueError('source metadata invalid')
        with sqlite3.connect(self.run.database_path.as_uri() + '?mode=ro', uri=True) as con:
            qsource = load_source_payload(con, run_id=self.run.run_id, evidence_id=ids['quote_evidence_id'])
            hsource = load_source_payload(con, run_id=self.run.run_id, evidence_id=ids['history_evidence_id'])
        if not qsource or not hsource:
            raise ValueError('persisted provider source receipt and SHA required')
        if (hist_e.get('content_hash') != payload_sha256(hsource[0]) or
                quote_e.get('content_hash') != payload_sha256(qsource[0])):
            raise ValueError('source evidence content hash differs from provider source document')
        with sqlite3.connect(self.run.database_path.as_uri() + '?mode=ro', uri=True) as con:
            row = con.execute("SELECT resolved_identifier FROM instrument_resolutions WHERE run_id=? AND requested_identifier=? AND resolution_status='RESOLVED'",(self.run.run_id,iid)).fetchone()
        if not row:
            raise ValueError('run resolved instrument listing unavailable')
        listing_id = row[0]
        if hsource[1] == 'yahoo_chart_native_monthly_v1':
            return self._native_monthly_input(iid,currency,cutoff,ids,accepted,
                hist_e,quote_e,hmeta,qmeta,hsource,qsource,listing_id,qprice)
        if (hmeta.get('ohlcv_receipt',{}).get('resolved_listing_id') != listing_id or
                qmeta.get('resolved_listing_id') != listing_id):
            raise ValueError('provider sources not bound to same resolved listing')
        observed = _aware(quote_e['observed_at'])
        retrieved = _aware(quote_e['retrieved_at'])
        if retrieved < observed or observed > cutoff:
            raise ValueError('quote timestamps not PIT eligible')
        if not qmeta.get('exchange') or not qmeta.get('market_session_date'):
            raise ValueError('persisted exchange and session date required for quote binding')
        ok, reason = verify_quote_body(qsource[0], qsource[1], instrument_id=listing_id,
            currency=currency, price=qprice, observed_at=observed,
            exchange=str(qmeta.get('exchange') or iid.partition(':')[0]),
            session_date=qmeta.get('market_session_date'), retrieved_at=retrieved)
        if not ok:
            raise ValueError('quote body mismatch: ' + str(reason))
        if hsource[1]=='yahoo_chart_ohlcv_v1':
            raw_chart=json.loads(hsource[0])['chart']['result'][0]['meta']
            if (type(raw_chart.get('regularMarketTime')) is not int or
                _aware(hist_e['published_at'])!=datetime.fromtimestamp(raw_chart['regularMarketTime'],tz=timezone.utc) or
                _aware(quote_e['published_at'])!=_aware(hist_e['published_at'])):
                raise ValueError('daily source publication receipt mismatch')
        receipt = hmeta.get('ohlcv_receipt')
        if not isinstance(receipt, dict) or not receipt.get('calendar_receipt') or not receipt.get('adjustment_receipt'):
            raise ValueError('persisted provider OHLCV adjustment/calendar receipts required')
        if receipt.get('analysis_eligible') is False or receipt.get('adjustment_verified') is not True:
            raise ValueError('verified adjustment receipt missing')
        sessions = receipt.get('expected_session_dates')
        if not isinstance(sessions, list) or not sessions or any(not isinstance(x, str) for x in sessions):
            raise ValueError('verified ordered session calendar required')
        parser, payload = hsource[1], hsource[0]
        arguments = dict(instrument_id=listing_id, analysis_as_of=cutoff,
                         adjustment_verified=True, adjustment_receipt=receipt['adjustment_receipt'],
                         calendar_receipt=receipt['calendar_receipt'], expected_session_dates=sessions)
        if parser == 'yahoo_chart_ohlcv_v1':
            parsed = parse_yahoo_chart_ohlcv(payload, source_url=hist_e.get('source_uri'), **arguments)
        elif parser == 'naver_ohlcv_v1':
            parsed = parse_naver_ohlcv(payload, currency=currency, request_url=hist_e.get('source_uri'), **arguments)
        else:
            raise ValueError('unrecognized OHLCV source parser; raw JSON is not authoritative')
        if not parsed.analysis_eligible or parsed.bar_set is None:
            raise ValueError('canonical BarSet failed analysis_eligible')
        bars = parsed.bar_set.bars
        if any(b.instrument_id != listing_id or b.currency != currency or b.close_time.astimezone(timezone.utc) > cutoff or not b.is_complete for b in bars):
            raise ValueError('OHLCV identity/currency/incomplete/future mismatch')
        if parsed.bar_set.adjustment_mode != AdjustmentMode.SPLIT_ADJUSTED:
            raise ValueError('only split-adjusted verified provider history supported')
        # A user-provided row ID or self-hashed JSON cannot establish a corporate
        # action factor. Re-parse an independent, selected provider action body.
        conversion_id = qmeta.get('verified_adjustment_conversion_ref')
        if qmeta.get('price_basis') != 'split-adjusted' or not isinstance(conversion_id, str):
            raise ValueError('nominal quote requires independently bound split conversion')
        conversion = accepted(conversion_id)
        if conversion.get('metric') != 'price_adjustment_conversion':
            raise ValueError('conversion evidence has wrong semantic metric')
        if hsource[1]=='yahoo_chart_ohlcv_v1' and _aware(conversion['published_at'])!=_aware(hist_e['published_at']):
            raise ValueError('daily split conversion publication differs from verified source')
        with sqlite3.connect(self.run.database_path.as_uri() + '?mode=ro', uri=True) as con:
            source_conversion = load_source_payload(con, run_id=self.run.run_id, evidence_id=conversion_id)
        if not source_conversion or conversion.get('content_hash') != payload_sha256(source_conversion[0]):
            raise ValueError('conversion must have independent unchanged provider source')
        cmeta = json.loads(conversion.get('metadata_json') or '{}')
        if (source_conversion[1] != 'yahoo_split_events_v1' or
                conversion.get('source_uri') != hist_e.get('source_uri') or
                source_conversion[0] != hsource[0] or
                cmeta.get('source_sha256') != payload_sha256(hsource[0]) or
                cmeta.get('direction') != 'nominal_to_split_adjusted' or
                cmeta.get('price_basis') != 'split-adjusted' or
                cmeta.get('currency') != currency or cmeta.get('instrument_id') != iid or cmeta.get('resolved_listing_id') != listing_id or
                cmeta.get('quote_evidence_id') != ids['quote_evidence_id'] or
                cmeta.get('history_evidence_id') != ids['history_evidence_id']):
            raise ValueError('conversion provenance/context/source mismatch')
        factor = Decimal(str(cmeta.get('factor', 'NaN')))
        if not factor.is_finite() or factor <= 0 or factor != Decimal('1'):
            raise ValueError('only verified zero-split factor=1 provider contracts supported')
        provider_chart = json.loads(hsource[0])
        try:
            chart = provider_chart['chart']['result'][0]
            if (chart['meta']['symbol'].upper() not in {listing_id.split(':')[-1].upper(), listing_id.split(':')[-1].upper()+'.T'}
                    or chart['meta']['currency'].upper() != currency
                    or 'events' not in chart or chart['events'].get('splits') != {}):
                raise ValueError('provider action history is not an explicit no-split response')
        except (KeyError, TypeError, AttributeError) as exc:
            raise ValueError('provider action history missing') from exc
        # Do not silently ignore a claimed factor or effective date.
        if Decimal(str(qmeta.get('conversion_factor', 'NaN'))) != factor or not cmeta.get('effective_at'):
            raise ValueError('quote conversion factor/effective time mismatch')
        effective = _aware(cmeta['effective_at'])
        if effective > cutoff or effective.date() != _aware(quote_e['observed_at']).date():
            raise ValueError('conversion effective timestamp is not bound to quote')
        qprice = qprice * factor
        tz = ZoneInfo(str(receipt.get('calendar_timezone', 'UTC')))
        from investment_stack.freshness import get_pinned_calendar
        exchange = str(qmeta['exchange'])
        schedule = get_pinned_calendar(exchange)
        if (schedule is None or not schedule.is_pinned or schedule.currency != currency or
                schedule.timezone != str(tz) or
                receipt.get('calendar_receipt') != schedule.schedule_id or
                receipt.get('calendar_source_urls') != list(schedule.source_urls)):
            raise ValueError('unbound calendar receipt or unsupported exchange/date')
        latest = schedule.latest_completed_session(cutoff)
        if (latest is None or qmeta.get('market_session_date') != latest.session_date.isoformat() or
                abs((_aware(quote_e['observed_at'])-latest.closes_at).total_seconds())>900):
            raise ValueError('quote is not bound to latest officially closed trading session')
        if (parser == 'yahoo_chart_ohlcv_v1' and
            (not bars or bars[-1].session_date != latest.session_date.isoformat() or
             bars[-1].close != qprice)):
            raise ValueError('latest quote price/session is not backed by closed provider daily bar')
        by_month = {}
        for b in bars:
            d = pd.Timestamp(b.session_date).date()
            k = (d.year, d.month)
            by_month.setdefault(k, []).append(b)
        months = sorted(by_month)
        # Exclude *current* calendar month regardless of morning/evening quote.
        months = [m for m in months if (
            (schedule.coverage_start.year, schedule.coverage_start.month) <= m
            < (cutoff.astimezone(tz).year, cutoff.astimezone(tz).month))]
        if len(months) < 8:
            raise ValueError('insufficient completed provider months')
        if any((b[0]-a[0])*12 + b[1]-a[1] != 1 for a,b in zip(months, months[1:])):
            raise ValueError('monthly history gaps')
        if months[-1] != ((cutoff.astimezone(tz).year - (cutoff.astimezone(tz).month == 1)),
                          (cutoff.astimezone(tz).month - 2) % 12 + 1):
            raise ValueError('latest completed month is missing or stale')
        from datetime import date
        if not schedule.covers(date(months[0][0], months[0][1], 1), date(months[-1][0], months[-1][1], monthrange(*months[-1])[1])):
            raise ValueError('calendar snapshot does not cover full first-to-last month')
        for year, month in months:
            actual = [b.session_date for b in by_month[(year,month)]]
            expected = [x.session_date.isoformat() for x in schedule.sessions
                        if (x.session_date.year,x.session_date.month)==(year,month)]
            if not expected or actual != expected:
                raise ValueError('full exchange-session calendar mismatch: missing/extra/unordered session')
        if sessions != [b.session_date for b in bars]:
            raise ValueError('provided expected sessions do not equal persisted bar dates')
        dates = [datetime(y, m, monthrange(y,m)[1], tzinfo=tz) for y,m in months]
        # Note: dates are local *civil* month end labels, not re-labeled UTC instants.
        closes = [float(by_month[m][-1].close) for m in months]
        # Amount is accepted only when directly reported by the raw provider per day.
        # Never estimate trading amount using close * volume.
        daily_amount = {}
        try:
            if parser == 'naver_ohlcv_v1':
                obj = json.loads(payload)
                items = obj['priceInfos']
                for entry in items:
                    d = entry['localDate']
                    key = f'{d[:4]}-{d[4:6]}-{d[6:8]}'
                    daily_amount[key] = entry.get('accumulatedTradingValue')
            elif parser == 'yahoo_chart_ohlcv_v1':
                obj = json.loads(payload)['chart']['result'][0]
                raw_dates = obj['timestamp']
                values = obj['indicators']['quote'][0].get('amount')
                if isinstance(values, list) and len(values) == len(raw_dates):
                    for epoch, value in zip(raw_dates, values):
                        key = datetime.fromtimestamp(epoch, tz).date().isoformat()
                        daily_amount[key] = value
        except (TypeError, ValueError, KeyError, IndexError):
            daily_amount = {}
        needed = [b.session_date for m in months for b in by_month[m]]
        amounts_ok = bool(needed) and all(d in daily_amount and daily_amount[d] is not None for d in needed)
        if amounts_ok:
            try:
                amounts_ok = all(Decimal(str(daily_amount[d])).is_finite() and Decimal(str(daily_amount[d])) >= 0 for d in needed)
            except (ValueError, ArithmeticError): amounts_ok = False
        monthly = []
        for m in months:
            bs = by_month[m]
            bar = {'open':float(bs[0].open),'high':float(max(b.high for b in bs)),
                   'low':float(min(b.low for b in bs)),'close':float(bs[-1].close),
                   'volume':float(sum(b.volume for b in bs))}
            if amounts_ok:
                bar['amount'] = float(sum(Decimal(str(daily_amount[b.session_date])) for b in bs))
            monthly.append(bar)
        frame = pd.DataFrame(monthly, index=pd.DatetimeIndex(dates))
        return closes, dates, frame, float(qprice), (ids['history_evidence_id'], ids['quote_evidence_id'], str(qmeta['verified_adjustment_conversion_ref'])), {
            'source_sha256': payload_sha256(payload), 'quote_source_sha256':payload_sha256(qsource[0]),
            'origin':dates[-1].isoformat(), 'window_start':dates[0].isoformat(),
            'window_end':dates[-1].isoformat(), 'calendar_timezone':str(tz),
            'price_basis':'split-adjusted', 'conversion_receipt':qmeta['verified_adjustment_conversion_ref'],
            'transform':'completed-month-ohlcv-v2-exchange-session-bound',
            'amount':'verified daily source sum' if amounts_ok else 'unavailable; Kronos requires source amount',
        }

    def _native_monthly_input(self, iid, currency, cutoff, ids, accepted,
                              hist_e, quote_e, hmeta, qmeta, hsource, qsource, listing_id, qprice):
        """Revalidate actual two-body same-run Yahoo monthly/daily contract.

        The monthly publisher cadence replaces the unavailable multi-year
        pinned daily session schedule, never claims to be such a schedule.
        """
        from investment_stack.providers.yahoo_native_months import parse_yahoo_native_months
        from investment_stack.providers.ohlcv import parse_yahoo_chart_ohlcv
        from investment_stack.providers.capture import market_urls
        from investment_stack.providers.market_quotes import parse_yahoo_quote
        from investment_stack.evidence.source_receipt import payload_sha256,verify_quote_body
        from investment_stack.freshness import get_pinned_calendar
        from zoneinfo import ZoneInfo
        from calendar import monthrange
        import pandas as pd
        receipt=hmeta.get('ohlcv_receipt')
        if not isinstance(receipt,dict) or receipt.get('resolved_listing_id')!=listing_id:
            raise ValueError('native monthly listing/source receipt missing')
        native=parse_yahoo_native_months(hsource[0],source_url=hist_e['source_uri'],
            listing_id=listing_id,currency=currency,cutoff=cutoff)
        if (receipt.get('native_interval')!='1mo' or receipt.get('range')!='5y' or
            receipt.get('calendar_timezone')!=native.timezone or
            receipt.get('calendar_receipt')!='provider:yahoo:native-monthly-closed:'+payload_sha256(hsource[0]) or
            receipt.get('adjustment_receipt')!='provider:yahoo:no-splits:'+payload_sha256(hsource[0]) or
            receipt.get('adjustment_verified') is not True or
            receipt.get('completed_count')!=len(native.months) or
            receipt.get('quote_source_sha256')!=payload_sha256(qsource[0]) or
            receipt.get('first_closed_month')!=f'{native.months[0].year:04d}-{native.months[0].month:02d}' or
            receipt.get('last_closed_month')!=f'{native.months[-1].year:04d}-{native.months[-1].month:02d}'):
            raise ValueError('monthly provenance not identical to native parser results')
        monthly_meta=json.loads(hsource[0])['chart']['result'][0]['meta']
        daily_meta=json.loads(qsource[0])['chart']['result'][0]['meta']
        if (type(monthly_meta.get('regularMarketTime')) is not int or
            type(daily_meta.get('regularMarketTime')) is not int or
            monthly_meta['regularMarketTime']!=daily_meta['regularMarketTime'] or
            _aware(quote_e['published_at'])!=datetime.fromtimestamp(monthly_meta['regularMarketTime'],tz=timezone.utc) or
            _aware(hist_e['published_at'])!=_aware(quote_e['published_at']) or
            Decimal(str(monthly_meta.get('regularMarketPrice','NaN'))) != qprice):
            raise ValueError('monthly no-split ledger clock/price does not cover latest quote')
        conversion_id=qmeta.get('verified_adjustment_conversion_ref')
        if not isinstance(conversion_id,str) or qmeta.get('price_basis')!='split-adjusted' or qmeta.get('resolved_listing_id')!=listing_id:
            raise ValueError('split-adjusted quote conversion not bound')
        conversion=accepted(conversion_id)
        if conversion.get('metric')!='price_adjustment_conversion':
            raise ValueError('native conversion is not a conversion source')
        if (_aware(conversion['published_at'])!=_aware(hist_e['published_at']) or
            _aware(conversion['observed_at'])!=_aware(quote_e['observed_at'])):
            raise ValueError('native conversion observed/publication time not source-bound')
        with sqlite3.connect(self.run.database_path.as_uri()+'?mode=ro',uri=True) as con:
            csrc=load_source_payload(con,run_id=self.run.run_id,evidence_id=conversion_id)
        if (not csrc or csrc[1]!='yahoo_native_no_splits_v1' or csrc[0]!=hsource[0] or
            conversion.get('content_hash')!=payload_sha256(hsource[0]) or
            conversion.get('source_uri')!=hist_e.get('source_uri')):
            raise ValueError('native provider corporate action source receipt invalid')
        cm=json.loads(conversion.get('metadata_json') or '{}')
        if (cm.get('source_sha256')!=payload_sha256(hsource[0]) or
            cm.get('quote_source_sha256')!=payload_sha256(qsource[0]) or
            cm.get('instrument_id')!=iid or cm.get('resolved_listing_id')!=listing_id or
            cm.get('currency')!=currency or cm.get('price_basis')!='split-adjusted' or
            cm.get('direction')!='nominal_to_split_adjusted' or
            cm.get('history_evidence_id')!=ids['history_evidence_id'] or
            cm.get('quote_evidence_id')!=ids['quote_evidence_id'] or
            Decimal(str(cm.get('factor','NaN')))!=Decimal(1) or
            Decimal(str(qmeta.get('conversion_factor','NaN')))!=Decimal(1) or
            _aware(cm.get('effective_at'))!=_aware(quote_e['observed_at'])):
            raise ValueError('native price conversion factor/identity/time mismatch')
        exchange=qmeta.get('exchange');schedule=get_pinned_calendar(exchange)
        if (schedule is None or not schedule.is_pinned or schedule.currency!=currency or
            schedule.timezone!=native.timezone):
            raise ValueError('latest daily quote calendar missing/mismatched')
        native_quote_url=hist_e['source_uri'].replace('?interval=1mo&range=5y&events=div%2Csplits',
                            '?interval=1d&range=5d&events=div%2Csplits')
        if quote_e.get('source_uri')!=native_quote_url:
            raise ValueError('native monthly history and daily quote URL identity mismatch')
        daily_obj=json.loads(qsource[0])['chart']['result'][0]
        daily_events=daily_obj.get('events',{})
        if (daily_obj.get('meta',{}).get('dataGranularity')!='1d' or
            daily_obj.get('meta',{}).get('instrumentType')!='EQUITY' or
            not isinstance(daily_events,dict) or set(daily_events)-{'dividends','splits'} or
            daily_events.get('splits',{})!={} or
            not isinstance(daily_events.get('dividends',{}),dict)):
            raise ValueError('latest daily quote interval or event schema invalid')
        latest=schedule.latest_completed_session(cutoff)
        if latest is None or qmeta.get('market_session_date')!=latest.session_date.isoformat():
            raise ValueError('latest closed daily quote schedule mismatch')
        quoted=parse_yahoo_quote(qsource[0],instrument_id=listing_id,
            retrieved_at=_aware(quote_e['retrieved_at']),source_url=quote_e['source_uri']).quote
        if quoted is None or quoted.price!=qprice or quoted.market_session_date!=latest.session_date.isoformat():
            raise ValueError('quoted value/session mismatch')
        ok,reason=verify_quote_body(qsource[0],qsource[1],instrument_id=listing_id,currency=currency,
            price=qprice,observed_at=_aware(quote_e['observed_at']),exchange=exchange,
            session_date=qmeta.get('market_session_date'),retrieved_at=_aware(quote_e['retrieved_at']))
        if not ok:raise ValueError('quote body mismatch: '+str(reason))
        if abs((_aware(quote_e['observed_at'])-latest.closes_at).total_seconds())>900:
            raise ValueError('latest daily source does not represent closed market price')
        daily=parse_yahoo_chart_ohlcv(qsource[0],instrument_id=listing_id,source_url=quote_e['source_uri'],
            analysis_as_of=cutoff,adjustment_verified=True,adjustment_receipt=cm['source_sha256'],
            calendar_receipt=schedule.schedule_id)
        if (not daily.bar_set or daily.discarded_bars or daily.error_reasons or
            not daily.bar_set.bars or daily.bar_set.bars[-1].session_date!=latest.session_date.isoformat() or
            daily.bar_set.bars[-1].close != qprice):
            raise ValueError('latest quote not backed by canonical closed daily source')
        tz=ZoneInfo(native.timezone)
        dates=[datetime(m.year,m.month,monthrange(m.year,m.month)[1],tzinfo=tz) for m in native.months]
        frame_data=[{'open':float(m.open),'high':float(m.high),'low':float(m.low),'close':float(m.close),
                     'volume':float(m.volume),**({'amount':float(m.amount)} if m.amount is not None else {})}
                    for m in native.months]
        if any(m.amount is None for m in native.months):
            for data in frame_data:data.pop('amount',None)
        frame=pd.DataFrame(frame_data,index=pd.DatetimeIndex(dates))
        return ([float(m.close) for m in native.months], dates, frame, float(qprice),
               (ids['history_evidence_id'],ids['quote_evidence_id'],conversion_id),{
               'source_sha256':payload_sha256(hsource[0]),'quote_source_sha256':payload_sha256(qsource[0]),
               'origin':dates[-1].isoformat(),'window_start':dates[0].isoformat(),
               'window_end':dates[-1].isoformat(),'calendar_timezone':native.timezone,
               'price_basis':'split-adjusted','conversion_receipt':conversion_id,
               'transform':'yahoo-native-closed-months-v1-source-and-daily-quote',
               'amount':'source-native provided' if 'amount' in frame else 'unavailable; Yahoo native source amount absent',
               'month_completeness':'provider native completed interval=1mo; no fabricated historical daily sessions'})

    @staticmethod
    def _bound_decimal_evidence(evidences, eid, iid, currency, cutoff, *, metric, unit,
                                status=('CONFIRMED','OFFICIAL','VERIFIED')):
        e=evidences.get(eid)
        if (not isinstance(eid,str) or not e or e.get('instrument_id')!=iid or
            e.get('currency')!=currency or e.get('selection_state')!='SELECTED' or
            e.get('official_confirmation_status') not in status or
            e.get('freshness_status') not in ('FRESH','LAST_VALID_CLOSE') or
            e.get('metric')!=metric or e.get('unit')!=unit):
            raise ValueError('selected per-field evidence metric/unit/identity/status mismatch')
        observed,published,retrieved=(_aware(e.get(x)) for x in ('observed_at','published_at','retrieved_at'))
        if observed>cutoff or published>cutoff or retrieved<max(observed,published):
            raise ValueError('field evidence is not point-in-time eligible')
        try:
            value=Decimal(str(json.loads(e['value_text'])))
        except (TypeError,ValueError,ArithmeticError) as exc:
            raise ValueError('field numeric evidence not parseable') from exc
        if not value.is_finite():raise ValueError('field numeric evidence nonfinite')
        if metric.startswith('assumption:'):
            md=json.loads(e.get('metadata_json') or '{}')
            if (not isinstance(md,dict) or md.get('assumption_kind')!='MODEL_ASSUMPTION' or
                not isinstance(md.get('assumption_source'),str) or not md['assumption_source'].strip() or
                _aware(md.get('assumption_as_of'))>cutoff):
                raise ValueError('selected assumption lacks typed modeling-as-of/source provenance')
        return value

    @staticmethod
    def _strict_monetary_unit(unit, currency, *, per_share, metadata):
        """Allowlist the *source* monetary dimension before MAIN normalization.

        The generic Phase5 normalizer trusts a currency header and defaults an
        unknown named scale to one. That is appropriate for exploratory Phase5
        but insufficient to attest a selected, same-run AI research witness.
        This parser accepts exact currency tokens and the already-supported MAIN
        scale names only; substrings such as ``USD percent`` are never money.
        """
        if not isinstance(unit, str) or not unit or unit != unit.strip():
            return False
        if currency not in ('USD', 'JPY', 'KRW'):
            return False
        from investment_stack.deep_research import (
            _CURRENCY_MARKERS, _NAMED_SCALES, _ABBREVIATED_SCALES,
            _EXPLICIT_SCALE_FIELDS, _explicit_scale,
        )
        import re

        body = unit
        suffix = re.search(r'\s*/\s*(?:share|shares|주)\s*$', body, flags=re.I)
        if suffix:
            body = body[:suffix.start()].strip()
        elif body.startswith('주당'):
            body = body[2:].strip()
            suffix = True
        if bool(suffix) != per_share:
            return False
        # Recognize the complete monetary unit, never a substring of a ratio,
        # a competing currency or an otherwise unknown label.
        symbols = sorted({v for vals in _CURRENCY_MARKERS.values() for v in vals}, key=len, reverse=True)
        recognized = []
        for symbol in symbols:
            if body.upper() == symbol.upper():
                recognized.append((symbol, ''))
            elif body.upper().startswith(symbol.upper() + ' '):
                recognized.append((symbol, body[len(symbol):].strip()))
            elif body.upper().endswith(' ' + symbol.upper()):
                recognized.append((symbol, body[:-len(symbol)].strip()))
            # CJK currency marks follow a scale without whitespace (百万円).
            elif not symbol.isascii() and body.endswith(symbol):
                recognized.append((symbol, body[:-len(symbol)].strip()))
        if len(recognized) != 1:
            return False
        symbol, scale_label = recognized[0]
        if symbol not in _CURRENCY_MARKERS[currency]:
            return False
        accepted_scales = {alias.casefold(): factor
                           for names, factor in _NAMED_SCALES for alias in names}
        accepted_scales.update({alias.casefold(): factor for alias, factor in _ABBREVIATED_SCALES.items()})
        if scale_label and scale_label.casefold() not in accepted_scales:
            return False
        unit_scale = accepted_scales[scale_label.casefold()] if scale_label else Decimal('1')
        explicit = [metadata[k] for k in _EXPLICIT_SCALE_FIELDS if metadata.get(k) is not None]
        if len(explicit) > 1:
            return False
        if explicit:
            from investment_stack.providers.models import ProviderObservation
            probe = ProviderObservation(evidence_type='financial', source_name='scale check',
                source_url=None, source_tier=1, provider_id='selected_receipt',
                value=Decimal('1'), unit=unit, currency=currency,
                instrument_id='unit-validation', metric='revenue', metadata=metadata)
            claimed = _explicit_scale(probe)
            if claimed is None or claimed != unit_scale:
                return False
        return True

    @staticmethod
    def _numeric_source(evidences, eid, iid, currency, cutoff, metric):
        """Read one selected numeric fact with its *source* dimension/scale.

        Use the MAIN normalization rules, not a calculation's claimed output
        unit. Normalized evidence is compared with the persisted analyzer
        receipt in base currency or per-share units. No inferred multiplier.
        """
        from investment_stack.deep_research import _normalize_metric_value
        from investment_stack.providers.models import ProviderObservation

        ev=evidences.get(eid)
        if (not ev or ev.get('instrument_id')!=iid or
            ev.get('currency') not in (None,currency) or
            ev.get('metric')!=metric or
            ev.get('selection_state')!='SELECTED' or
            ev.get('official_confirmation_status') not in ('CONFIRMED','VERIFIED','OFFICIAL') or
            ev.get('freshness_status') not in ('FRESH','LAST_VALID_CLOSE')):
            return None
        try:
            times=[_aware(ev[k]) for k in ('observed_at','published_at','retrieved_at')]
            if times[0]>cutoff or times[1]>cutoff or times[2]<max(times[:2]):return None
            raw=json.loads(ev['value_text'])
            if raw is None or isinstance(raw,bool):return None
            value=Decimal(str(raw))
            if not value.is_finite():return None
            unit=ev.get('unit')
            md=json.loads(ev.get('metadata_json') or '{}')
            if not isinstance(md,dict):return None
            if metric=='current_price':
                # A quoted price is a per-share monetary price, never shares.
                # Native market quotes may use a bare currency unit; non-market
                # financial sources must explicitly label a per-share price.
                if unit not in (currency, f'{currency}/share') or (
                    unit==currency and ev.get('evidence_type') not in ('market','price')):
                    return None
                if any(md.get(k) not in (None,1,'1') for k in ('unit_multiplier','value_multiplier','unit_scale','value_scale')):
                    return None
                return value
            if metric in ('tax_rate',):
                return value if unit in ('ratio','decimal') else None
            if metric in ('pe','pb','ev_to_ebitda','price_to_sales'):
                # Earlier v3 direct multiple facts have no unit; this applies
                # only to a source fact with the same metric, never raw money.
                return value if unit in (None,'multiple') else None
            total_money = ('revenue','prior_revenue','operating_income','net_income',
                           'cash_from_operations','capex','total_debt','cash','equity',
                           'average_equity','invested_capital','current_assets',
                           'current_liabilities','enterprise_value','ebitda','market_cap')
            per_share_money = ('eps','book_value_per_share','dividend_per_share')
            if metric in total_money + per_share_money and not (
                PostValuationForecastService._strict_monetary_unit(
                    unit, currency, per_share=metric in per_share_money, metadata=md)):
                return None
            obs=ProviderObservation(evidence_type=ev.get('evidence_type') or 'financial',
                source_name=ev.get('source_name') or 'bound canonical evidence',
                source_url=ev.get('source_uri'),source_tier=1,
                provider_id=ev.get('provider_id') or 'selected_receipt',
                value=value,unit=unit,currency=ev.get('currency'),
                instrument_id=iid,metric=metric,metadata=md)
            normalized,reason=_normalize_metric_value(metric,value,obs,target_currency=currency)
            if reason or normalized is None or not normalized.is_finite():return None
            # The canonical normalizer allows missing monetary units for a
            # few non-web providers. Forecast witnessing is stricter: no
            # unlabeled money or per-share prices become verified evidence.
            if metric in ('revenue','prior_revenue','operating_income','net_income',
                          'cash_from_operations','capex','total_debt','cash','equity',
                          'average_equity','invested_capital','current_assets',
                          'current_liabilities','enterprise_value','ebitda','market_cap',
                          'eps','book_value_per_share','dividend_per_share') and not unit:
                return None
            return normalized
        except (ValueError,TypeError,KeyError,ArithmeticError,OverflowError):return None

    @staticmethod
    def _research_formula_specs(currency):
        return {
            'EQUITY_FUNDAMENTAL':{
                'revenue_growth':('revenue / prior_revenue - 1',('revenue','prior_revenue'),'ratio'),
                'operating_margin':('operating_income / revenue',('operating_income','revenue'),'ratio'),
                'net_margin':('net_income / revenue',('net_income','revenue'),'ratio'),
                'free_cash_flow':('cash_from_operations - capex; not an FCFF or FCFE bridge',('cash_from_operations','capex'),currency),
                'free_cash_flow_margin':('free_cash_flow / revenue',('cash_from_operations','capex','revenue'),'ratio'),
                'debt_to_equity':('total_debt / equity',('total_debt','equity'),'ratio'),
                'current_ratio':('current_assets / current_liabilities',('current_assets','current_liabilities'),'ratio'),
                'roe':('net_income / average_equity',('net_income','average_equity'),'ratio'),
                'roic':('operating_income * (1-tax_rate) / invested_capital',('operating_income','tax_rate','invested_capital'),'ratio'),
            },
            'EQUITY_VALUATION':{
                'pe':('current_price / eps',('current_price','eps'),'multiple'),
                'pb':('current_price / book_value_per_share',('current_price','book_value_per_share'),'multiple'),
                'ev_to_ebitda':('enterprise_value / ebitda',('enterprise_value','ebitda'),'multiple'),
                'price_to_sales':('market_cap / revenue',('market_cap','revenue'),'multiple'),
                'dividend_yield':('dividend_per_share / current_price',('dividend_per_share','current_price'),'ratio'),
            },
        }

    @staticmethod
    def _growth_period_bound(evidences, refs, cutoff):
        """Bind *actual* annual/TTM revenue periods to publication and PIT dates.

        Fiscal period endpoints are calendar dates, never fabricated UTC midnight
        instants. Each source's declared aware timestamp offset is the calendar
        for comparing its observed/published day and the corresponding cutoff day.
        Future guidance requires a separate typed assumption; it is not a
        historical, confirmed ``revenue_growth`` witness.
        """
        from datetime import date

        def date_info(name):
            rows=[evidences[x] for x in refs if evidences[x].get('metric')==name]
            if len(rows)!=1:return None
            row=rows[0]
            try:
                metadata=json.loads(row.get('metadata_json') or '{}')
                if not isinstance(metadata,dict):return None
                end_text=metadata['period_end']
                end=date.fromisoformat(end_text)
                if end_text!=end.isoformat():return None  # strict YYYY-MM-DD
                start_value=metadata.get('period_start') or metadata.get('start')
                start=date.fromisoformat(start_value) if start_value else None
                if start is not None and start_value!=start.isoformat():return None
                basis=metadata.get('flow_basis') or metadata.get('reporting_frequency')
                account=metadata.get('basis') or metadata.get('accounting_standard')
                if not isinstance(basis,str) or (start is not None and start>end):return None
                # The canonical SEC companyfacts parser identifies annual flow
                # periods by their *inclusive* reported length: 330..400 days
                # (providers/adapters.py). An explicit start/end shorter or
                # longer than that cannot certify historical ANNUAL/TTM growth.
                # A missing start remains unsupported partial provenance; do
                # not invent one or infer a 365-day fiscal year.
                if (start is not None and basis.upper() in ('ANNUAL','FY','FULL_YEAR','TTM')
                        and not 330 <= (end-start).days+1 <= 400):
                    return None
                for clock_key in ('observed_at','published_at'):
                    text=row.get(clock_key)
                    clock=(datetime.fromisoformat(text.replace('Z','+00:00'))
                           if isinstance(text,str) else text)
                    if not isinstance(clock,datetime) or clock.utcoffset() is None:return None
                    # Local calendar dates as recorded by the source; no
                    # timezone-free datetime comparison or invented midnight.
                    if end>clock.date() or end>cutoff.astimezone(clock.tzinfo).date():
                        return None
                return end,start,basis.upper(),account
            except (KeyError,TypeError,ValueError,OverflowError):return None

        newer,older=date_info('revenue'),date_info('prior_revenue')
        if not newer or not older:return False
        if newer[2] not in ('ANNUAL','FY','FULL_YEAR','TTM') or newer[2]!=older[2] or newer[3]!=older[3]:return False
        n,ns=newer[:2];o,os=older[:2]
        if not 364 <= (n-o).days <= 366:return False
        if ns is not None and os is not None:
            if not 364 <= (ns-os).days <= 366:return False
            if abs(((n-ns).days)-((o-os).days))>2:return False
        return True

    @classmethod
    def _verified_prior_metric(cls,m,refs,evidences,iid,currency,cutoff):
        """Legacy direct metric support, requiring selected same-name value binding.

        An unavailable metric is checked separately and never counts as the
        required numeric witness. Derived metrics take the canonical path.
        """
        if not isinstance(m,dict) or m.get('status') not in ('COMPLETE','PARTIAL') or (
            not isinstance(m.get('name'),str) or m['name'] not in
            {name for group in cls._research_formula_specs(currency).values() for name in group}):
            return False
        ids=m.get('evidence_ids')
        if not isinstance(ids,list) or not ids or not set(ids)<=set(refs):return False
        try:
            value=Decimal(str(m['value']))
            if not value.is_finite():return False
        except (ValueError,TypeError,ArithmeticError,KeyError):return False
        unit=m.get('unit')
        name=m['name']
        allowed_unit=next((x[2] for group in cls._research_formula_specs(currency).values()
                            for key,x in group.items() if key==name),None)
        if unit not in (None,allowed_unit):return False
        return any(cls._numeric_source(evidences,eid,iid,currency,cutoff,name)==value for eid in ids)

    @classmethod
    def _verified_canonical_metrics(cls,kind,metrics,refs,evidences,iid,currency,cutoff,*,prior=False):
        """Recalculate supported MAIN analyzer metrics using selected typed raw facts.

        PARTIAL/UNAVAILABLE nulls do not invalidate a known-good witness. A
        mismatched supported numeric value, unknown metric, or invalid unit
        rejects the receipt rather than laundering a fabricated source.
        """
        if not isinstance(metrics,list) or not metrics:return False
        specs=cls._research_formula_specs(currency)[kind]
        raw={};sources={}
        supported={'revenue','prior_revenue','operating_income','net_income',
                   'cash_from_operations','capex','total_debt','cash','equity',
                   'average_equity','invested_capital','tax_rate','current_assets',
                   'current_liabilities','current_price','eps','book_value_per_share',
                   'enterprise_value','ebitda','market_cap','dividend_per_share'}
        for eid in refs:
            e=evidences[eid];name=e.get('metric')
            if name in supported:
                v=cls._numeric_source(evidences,eid,iid,currency,cutoff,name)
                if v is not None:
                    if name in raw and raw[name]!=v:return False
                    raw[name]=v;sources[name]=eid
        witnesses=0
        for m in metrics:
            if not isinstance(m,dict) or not isinstance(m.get('name'),str):return False
            name=m['name'];spec=specs.get(name)
            if spec is None:
                if (kind=='EQUITY_VALUATION' and (name=='dcf_value_per_share' or
                      name.startswith(('dcf_scenario_','dcf_sensitivity_','scenario_')))):
                    # Complex scenario/DCF numbers do not independently certify
                    # this source receipt, and cannot be a terminal anchor.
                    continue
                return False
            formula,deps,unit=spec
            nullable=m.get('value') is None
            allowed_formulas=(formula,'cash_from_operations - capex') if nullable and name=='free_cash_flow' else (formula,)
            if prior:allowed_formulas+= (None,)
            if m.get('formula') not in allowed_formulas or m.get('unit') not in ((unit,None) if prior else (unit,)):return False
            ids=m.get('evidence_ids')
            if not isinstance(ids,list) or not set(ids)<=set(refs):return False
            if m.get('value') is None:
                if m.get('status') not in ('UNAVAILABLE','PARTIAL'):return False
                continue
            if m.get('status') not in ('COMPLETE','PARTIAL'):return False
            try:
                actual=Decimal(str(m['value']))
                if not actual.is_finite():return False
            except (ValueError,TypeError,ArithmeticError):return False
            # Original imported standalone direct PE/multiple observations are
            # supported by a literal source equality, not claimed by a formula.
            if prior and m.get('formula') is None and cls._verified_prior_metric(
                m,refs,evidences,iid,currency,cutoff):
                witnesses+=1;continue
            if m.get('formula')!=formula or m.get('unit')!=unit:return False
            if not all(d in raw for d in deps):continue
            if not ids or not all(sources[d] in ids for d in deps):return False
            if name=='revenue_growth' and not cls._growth_period_bound(evidences,refs,cutoff):continue
            try:
                if name=='revenue_growth':expected=raw['revenue']/raw['prior_revenue']-1
                elif name=='free_cash_flow':expected=raw['cash_from_operations']-raw['capex']
                elif name=='free_cash_flow_margin':expected=(raw['cash_from_operations']-raw['capex'])/raw['revenue']
                elif name=='roic':expected=raw['operating_income']*(1-raw['tax_rate'])/raw['invested_capital']
                else:
                    numerator,denominator=deps
                    expected=raw[numerator]/raw[denominator]
                if not expected.is_finite() or abs(expected-actual)>Decimal('1e-18'):return False
            except (ArithmeticError,ZeroDivisionError,KeyError,ValueError):return False
            witnesses+=1
        return witnesses>0

    def _research_and_anchor(self, iid: str, currency: str, cutoff: datetime, target: datetime):
        """Only independently confirmed canonical numeric research and typed terminal projections.

        A typed assumption is a scenario INPUT, never confirmed future earnings.
        The source input evidences must actually carry the exact saved values.
        """
        from investment_stack.forecasting.contracts import FundamentalAnchor
        ctx=self.run.fetch_phase6_context()
        evidences={r['evidence_id']:r for r in ctx['evidence'] if r['run_id']==self.run.run_id}
        def eligible(eid):
            e=evidences.get(eid)
            if not e or e.get('instrument_id')!=iid or e.get('selection_state')!='SELECTED' or e.get('currency') not in (None,currency) or e.get('official_confirmation_status') not in ('CONFIRMED','OFFICIAL','VERIFIED') or e.get('freshness_status') not in ('FRESH','LAST_VALID_CLOSE'):
                return False
            try:
                a,b,c=(_aware(e[x]) for x in ('observed_at','published_at','retrieved_at'))
                return a<=cutoff and b<=cutoff and c>=max(a,b)
            except (KeyError,TypeError,ValueError):return False
        approved={}; projections=[]
        for row in ctx['calculations']:
            if row.get('run_id')!=self.run.run_id:continue
            kind=row.get('calculation_name')
            try:
                inp=json.loads(row.get('inputs_json') or '{}'); result=json.loads(row.get('result_json') or '{}')
            except (ValueError,TypeError):continue
            if not isinstance(inp,dict) or not isinstance(result,dict) or result.get('subject')!=iid:continue
            refs=inp.get('evidence_ids')
            if not isinstance(refs,list) or not refs or len(set(refs))!=len(refs) or not all(eligible(x) for x in refs):continue
            if kind in ('EQUITY_FUNDAMENTAL','EQUITY_VALUATION'):
                if (result.get('analysis_type')!=kind or result.get('status') not in ('COMPLETE','PARTIAL') or
                    result.get('metadata',{}).get('currency')!=currency or
                    inp.get('subject',iid)!=iid):continue
                metrics=result.get('metrics')
                if not isinstance(metrics,list) or not metrics:continue
                if row.get('formula') != 'deterministic_phase5_asset_analysis':
                    continue
                if self._verified_canonical_metrics(kind, metrics, refs, evidences, iid, currency, cutoff):
                    approved[row['calculation_id']]=(row,inp,result)
            elif kind=='VALIDATED_PRIOR_RESEARCH':
                # The importer is the only accepted source of this name. Its
                # original run/evidence/calculation lineage must be present.
                if row.get('formula')!='explicit_validity_bounded_prior_import_v1' or not inp.get('source_run_id') or not inp.get('source_calculation_id'):
                    continue
                metas=[]
                for x in refs:
                    md=json.loads(evidences[x].get('metadata_json') or '{}');metas.append(md)
                if not all(md.get('imported_from_run_id')==inp['source_run_id'] and md.get('original_calculation_id')==inp['source_calculation_id'] and md.get('original_evidence_id') and _aware(md['research_valid_until'])>=cutoff for md in metas):
                    continue
                if (inp.get('source_analysis_type') not in ('EQUITY_FUNDAMENTAL','EQUITY_VALUATION') or
                    inp.get('source_analysis_status') not in ('COMPLETE','PARTIAL') or
                    result.get('source_analysis_type') != inp['source_analysis_type'] or
                    result.get('source_analysis_status') != inp['source_analysis_status'] or
                    not isinstance(inp.get('source_calculation_formula'),str) or
                    not inp['source_calculation_formula'] or
                    _aware(inp.get('source_analysis_as_of'))>cutoff or
                    (isinstance(inp.get('source_analysis_metadata'),dict) and
                     inp['source_analysis_metadata'].get('currency') not in (None,currency))):
                    continue
                metrics=result.get('metrics',())
                # The genuine v3 importer preserves original metric names, values
                # and per-evidence IDs, but does not certify numeric correctness.
                # Require an unchanged selected source value and usable status.
                origin_kind=inp['source_analysis_type']
                # Genuine v3 analyzer imports carry their original canonical
                # producer formula; legacy standalone direct facts still need
                # exact selected value, unit and metric binding.
                genuine=inp.get('source_calculation_formula')=='deterministic_phase5_asset_analysis'
                # A previously computed (rather than directly reported)
                # metric can only originate from the actual Phase5 analyzer.
                specs=self._research_formula_specs(currency)[origin_kind]
                if any(m.get('value') is not None and m.get('formula') is not None and
                       m.get('name') in specs and not genuine for m in metrics if isinstance(m,dict)):
                    continue
                if (result.get('subject')==iid and result.get('status','COMPLETE') not in
                    ('FAILED','ERROR','UNAVAILABLE') and isinstance(metrics,list) and metrics and
                    self._verified_canonical_metrics(origin_kind,metrics,refs,evidences,
                        iid,currency,cutoff,prior=True)):
                    approved[row['calculation_id']]=(row,inp,result)
            elif kind=='EQUITY_TERMINAL_PROJECTION':projections.append((row,inp,result,refs))
        valid_main={'EQUITY_FUNDAMENTAL','EQUITY_VALUATION'}<={r[0]['calculation_name'] for r in approved.values()}
        valid_prior=any(r[0]['calculation_name']=='VALIDATED_PRIOR_RESEARCH' for r in approved.values())
        if not valid_main and not valid_prior:
            raise ValueError('missing verified same-run numerical fundamental/valuation research receipts')
        reason='no explicit eligible EPS terminal projection; present DCF is not terminal'
        for row,inp,res,refs in projections:
            try:
                sources=inp.get('source_calculation_ids',())
                if (res.get('status')!='COMPLETE' or res.get('value_kind')!='terminal_price' or
                    res.get('target_semantics')!='terminal_price' or res.get('dividends_excluded') is not True or
                    res.get('price_basis')!='split-adjusted' or res.get('currency')!=currency or
                    res.get('formula_kind')!='eps_growth_terminal_pe_v1' or
                    row.get('formula')!='eps * (1 + annual_eps_growth) ** horizon_years * terminal_pe' or
                    _aware(res['target_date'])!=target or _aware(res['as_of'])>cutoff or
                    not isinstance(sources,list) or not sources or not set(sources)<=set(approved) or
                    not valid_main):
                    raise ValueError('unsupported terminal formula/status/horizon/identity/source research')
                fields=inp.get('fields'); expectations={
                   'eps':('eps',f'{currency}/share'),
                   'annual_eps_growth':('assumption:eps_growth_annual','decimal/year'),
                   'terminal_pe':('assumption:terminal_pe','multiple')}
                if not isinstance(fields,dict) or set(fields)!=set(expectations):raise ValueError('projection field bindings absent')
                if not isinstance(inp.get('evidence_ids'),list) or set(refs)!=set(inp['evidence_ids']):raise ValueError('source evidence set differs')
                values={}; used=[]
                for name,(metric,unit) in expectations.items():
                    field=fields[name]; eid=field['evidence_id']
                    if eid in used or eid not in refs or field.get('metric')!=metric or field.get('unit')!=unit or field.get('assumption_kind')!=('MODEL_ASSUMPTION' if name!='eps' else 'OBSERVED_EPS'):
                        raise ValueError('projection field kind/binding duplicate or mismatch')
                    used.append(eid)
                    v=self._bound_decimal_evidence(evidences,eid,iid,currency,cutoff,metric=metric,unit=unit)
                    if v!=Decimal(str(field['value'])):raise ValueError('projection saved value differs from selected evidence')
                    values[name]=v
                years=Decimal(str(inp['horizon_years']))
                if years!=Decimal(5) or values['eps']<=0 or values['terminal_pe']<=0 or values['annual_eps_growth']<=-1:
                    raise ValueError('projection horizon/assumptions out of supported scope')
                terminal=values['eps']*(Decimal(1)+values['annual_eps_growth'])**int(years)*values['terminal_pe']
                price=Decimal(str(res['terminal_price']))
                if not price.is_finite() or price<=0 or abs(price-terminal)>Decimal('0.00000001'):
                    raise ValueError('terminal price not equal to exact Decimal formula result')
                anchor=FundamentalAnchor(status='COMPLETE',instrument_id=iid,currency=currency,
                    target_date=target,price_basis='split-adjusted',value_kind='terminal_price',
                    as_of=_aware(res['as_of']),base=float(price),evidence_refs=tuple(refs),
                    assumption_refs=tuple(used[1:]),details={'source_calculation_id':row['calculation_id'],
                    'source_calculations':sources,'dividends_excluded':True,'assumptions_are_future_scenarios':True})
                anchor.validate()
                return anchor,tuple(dict.fromkeys((*refs,*used))),None
            except (ValueError,TypeError,KeyError,ArithmeticError,OverflowError,IndexError) as exc:
                reason='terminal projection rejected: '+str(exc)
        return None,(),reason

    def _produce_terminal_projection(self, iid, currency, cutoff, target):
        """Optional explicit JSON only BINDS selected same-run source evidence; it is not authority."""
        if self.config.terminal_projection_file is None:return
        raw=json.loads(self.config.terminal_projection_file.read_text(encoding='utf8'))
        if not isinstance(raw,dict) or iid not in raw:return
        spec=raw[iid]
        required={'as_of','target_date','currency','price_basis','horizon_years','fields'}
        selectors={'source_calculation_ids','source_calculation_selectors'}
        if (not isinstance(spec,dict) or not required<=set(spec) or
            set(spec)-required not in ({'source_calculation_ids'}, {'source_calculation_selectors'})):
            raise ValueError('typed terminal projection config malformed')
        if (_aware(spec['as_of'])>cutoff or _aware(spec['target_date'])!=target or spec['currency']!=currency or
            spec['price_basis']!='split-adjusted' or Decimal(str(spec['horizon_years']))!=5):
            raise ValueError('terminal projection explicit context mismatch')
        fields=spec['fields']
        if set(fields)!={'eps','annual_eps_growth','terminal_pe'}:raise ValueError('terminal projection fields missing')
        ctx=self.run.fetch_phase6_context();e={r['evidence_id']:r for r in ctx['evidence'] if r['run_id']==self.run.run_id}
        available={r['calculation_id']:r for r in ctx['calculations'] if r['run_id']==self.run.run_id}
        if 'source_calculation_selectors' in spec:
            selector=spec['source_calculation_selectors']
            if not isinstance(selector,dict) or set(selector)!={'fundamental','valuation'} or any(
                selector[k] != {'calculation_name':'EQUITY_'+k.upper()} for k in selector):
                raise ValueError('source calculation selectors require exact canonical research names')
            source_ids=[]
            for kind in ('EQUITY_FUNDAMENTAL','EQUITY_VALUATION'):
                candidates=[r['calculation_id'] for r in available.values()
                    if r['calculation_name']==kind and json.loads(r['result_json'] or '{}').get('subject')==iid]
                if len(candidates)!=1:raise ValueError('source calculation selector missing or ambiguous')
                source_ids.extend(candidates)
        else:
            source_ids=spec['source_calculation_ids']
        if (not isinstance(source_ids,list) or len(set(source_ids))!=2 or
            {available[x]['calculation_name'] for x in source_ids if x in available} !=
                {'EQUITY_FUNDAMENTAL','EQUITY_VALUATION'}):
            raise ValueError('terminal projection source calculation IDs not selected fundamental and valuation')
        for cid in source_ids:
            origin=json.loads(available[cid]['result_json'] or '{}')
            if origin.get('subject')!=iid or origin.get('analysis_type')!=available[cid]['calculation_name'] or origin.get('status') not in ('COMPLETE','PARTIAL') or not origin.get('metrics'):
                raise ValueError('terminal projection requires valid numerical source calculations')
        unitmetric={'eps':('eps',f'{currency}/share'),'annual_eps_growth':('assumption:eps_growth_annual','decimal/year'),'terminal_pe':('assumption:terminal_pe','multiple')}
        vals={};ids=[];resolved_field_ids={}
        for k,(metric,unit) in unitmetric.items():
            field=fields[k]
            expected_field_keys={'metric','unit','value','assumption_kind'}
            if (not isinstance(field,dict) or set(field)-expected_field_keys not in
                ({'evidence_id'},{'evidence_selector'})):
                raise ValueError('projection field must select exactly one evidence binding')
            if field.get('metric')!=metric or field.get('unit')!=unit or field.get('assumption_kind')!=('OBSERVED_EPS' if k=='eps' else 'MODEL_ASSUMPTION'):
                raise ValueError('terminal projection field metadata mismatch')
            if 'evidence_selector' in field:
                wanted=field['evidence_selector']
                if wanted!={'metric':metric,'unit':unit}:
                    raise ValueError('field evidence selector metric/unit mismatch')
                matches=[eid for eid,e in e.items() if e.get('instrument_id')==iid and
                    e.get('metric')==metric and e.get('unit')==unit and
                    e.get('selection_state')=='SELECTED']
                if len(matches)!=1:raise ValueError('field evidence selector missing or ambiguous')
                eid=matches[0]
            else:
                eid=field['evidence_id']
            ids.append(eid);resolved_field_ids[k]=eid
            v=self._bound_decimal_evidence(e,eid,iid,currency,cutoff,metric=metric,unit=unit)
            if v!=Decimal(str(field['value'])):raise ValueError('config value not backed by selected canonical evidence')
            vals[k]=v
        if len(set(ids))!=3 or vals['eps']<=0 or vals['annual_eps_growth']<=-1 or vals['terminal_pe']<=0:
            raise ValueError('terminal projection invalid evidence/assumption values')
        terminal=vals['eps']*(Decimal(1)+vals['annual_eps_growth'])**5*vals['terminal_pe']
        self.run.add_calculation(calculation_id='calc:terminal-forecast:'+uuid4().hex,
            calculation_name='EQUITY_TERMINAL_PROJECTION',
            formula='eps * (1 + annual_eps_growth) ** horizon_years * terminal_pe',
            inputs={'evidence_ids':ids,'source_calculation_ids':source_ids,
                    'fields':{k:{**v,'evidence_id':resolved_field_ids[k]} for k,v in fields.items()},'horizon_years':'5'},
            result={'subject':iid,'status':'COMPLETE','value_kind':'terminal_price',
                    'target_semantics':'terminal_price','dividends_excluded':True,
                    'price_basis':'split-adjusted','currency':currency,'as_of':spec['as_of'],
                    'target_date':spec['target_date'],'formula_kind':'eps_growth_terminal_pe_v1',
                    'terminal_price':str(terminal),'assumptions_are_scenarios':True})

    def _engine(self):
        if self.engine_factory is not None:
            return self.engine_factory(self.config)
        from investment_stack.forecasting.adapters.chronos2 import Chronos2Adapter
        from investment_stack.forecasting.adapters.kronos import KronosAdapter
        from investment_stack.forecasting.adapters.tabular_ml import TabularMLAdapter
        from investment_stack.forecasting.engine import ForecastingEngine
        adapters = []
        if self.config.chronos_model_dir:
            adapters.append(Chronos2Adapter(device_map='cpu', model_ref=str(self.config.chronos_model_dir)))
        if self.config.kronos_model_dir:
            adapters.append(KronosAdapter(model_ref=str(self.config.kronos_model_dir), tokenizer_ref=str(self.config.kronos_tokenizer_dir), source_root=str(self.config.kronos_source_root), device='cpu'))
        if self.config.xgboost_artifact:
            adapters.append(TabularMLAdapter(str(self.config.xgboost_artifact), model_id='xgboost-tabular-5y'))
        if self.config.lightgbm_artifact:
            adapters.append(TabularMLAdapter(str(self.config.lightgbm_artifact), model_id='lightgbm-tabular-5y'))
        return ForecastingEngine(adapters)

    def run_for_instruments(self, instrument_ids: tuple[str, ...], *, currency_by_id: Mapping[str, str]):
        if len(set(instrument_ids)) != len(instrument_ids):
            raise ValueError('duplicate forecast instrument')
        cutoff = _aware(self.run.fetch_metadata()['analysis_as_of'])
        results = {}
        sections=[]
        calculation_ids=[]
        all_refs=[]
        missing=[]
        for iid in instrument_ids:
            status='UNAVAILABLE'; reason=''; point=None; model_rows=[]; ensemble_id=None
            refs=(); extra={}; assessment={'status':'UNAVAILABLE','ranking_allowed':False}
            persisted=False; calc_id='calc:ai-forecast:'+uuid4().hex
            try:
                if not self.config.configured():
                    raise ValueError('no local model configured; no optional model imported')
                # Missing paths must not import a framework or attempt a download.
                paths = [p for p in (self.config.chronos_model_dir,
                         self.config.kronos_model_dir,self.config.kronos_tokenizer_dir,
                         self.config.kronos_source_root,self.config.xgboost_artifact,
                         self.config.lightgbm_artifact) if p is not None]
                if any(not p.exists() for p in paths):
                    raise ValueError('local pretrained model/artifact/source path unavailable; downloads disabled')
                currency = currency_by_id.get(iid)
                if not isinstance(currency,str) or not currency.strip():
                    raise ValueError('resolved instrument currency unavailable')
                if iid not in self.input_selections and self.source_collector is not None:
                    self.input_selections[iid] = self.source_collector.collect(iid,currency,cutoff)
                history, timestamps, ohlcv, quote, refs, extra = self._source_input(iid, currency, cutoff)
                from investment_stack.forecasting.contracts import ForecastRequest
                from investment_stack.forecasting.store import ForecastStore
                import pandas as pd
                origin = timestamps[-1]
                target = (pd.Timestamp(origin) + pd.offsets.MonthEnd(60)).to_pydatetime()
                request = ForecastRequest(instrument_id=iid,currency=currency,as_of=cutoff,
                    current_price=quote,target_date=target,horizon_steps=60,frequency='ME',
                    history=tuple(history),timestamps=tuple(timestamps),ohlcv=ohlcv,
                    metadata={'price_basis':'split-adjusted', 'origin':'last_completed_month',
                              'source_evidence_refs':list(refs), 'input_sha256':extra['source_sha256']})
                request.validate()
                anchor_reason=None;anchor_refs=()
                anchor=None
                if extra.get('transform') in ('completed-month-ohlcv-v2-exchange-session-bound','yahoo-native-closed-months-v1-source-and-daily-quote'):
                    projection_rejection=None
                    try:
                        self._produce_terminal_projection(iid,currency,cutoff,target)
                    except (ValueError,TypeError,KeyError,ArithmeticError,OverflowError) as projection_error:
                        projection_rejection='terminal projection rejected: '+str(projection_error)
                    anchor, anchor_refs, anchor_reason = self._research_and_anchor(iid,currency,cutoff,target)
                    if projection_rejection: anchor_reason=(projection_rejection+'; '+(anchor_reason or ''))
                    refs=tuple(dict.fromkeys((*refs,*anchor_refs)))
                engine = self._engine()
                with _offline_inference_scope():
                    combined, model_results = engine.run(request, anchor=anchor, reliability=None)
                assessment = dict(combined.details.get('assessment') or assessment)
                # No double-write: engine called WITHOUT run_db_path.
                persist_models = {m.model_id:m for m in model_results}
                for component in combined.components:
                    if component.model_id=='fundamental-anchor':
                        persist_models[component.model_id]=component
                status = combined.status
                point = combined.point
                if point is None:
                    reason = '; '.join(f'{m.model_id}:{m.status}:{m.error or "no point"}' for m in model_results)
                else:
                    concerns = [f'{m.model_id}:{m.status}:{m.error or "unavailable"}' for m in model_results if m.status != 'COMPLETE']
                    if anchor_reason: concerns.append(anchor_reason)
                    if combined.status != 'COMPLETE':concerns.append('conditional/partial ensemble; not a validated price forecast')
                    reason='; '.join(concerns)
                extra.update({'target':target.isoformat(),'horizon_steps':60,
                              'actual_elapsed_years':(target.astimezone(timezone.utc)-cutoff).total_seconds()/86400/365.25,
                              'current_price':quote, 'assessment':assessment,
                              'anchor_source_refs':list(anchor_refs),'anchor_eligibility_reason':anchor_reason})
                calc_id='calc:ai-forecast:'+uuid4().hex
                def atomic_calc(ids, eid):
                    saved = [{'model_id':m.model_id,'run_row_id':ref,'status':m.status,'point':m.point,
                              'error':m.error,'validation_level':m.validation_level}
                             for m,ref in zip(persist_models.values(),ids)]
                    years=extra['actual_elapsed_years']
                    price_cagr=(point/quote)**(1/years)-1 if point is not None and years>0 else None
                    provenance={**extra,'model_statuses':saved,'ensemble_id':eid}
                    return {'calculation_id':calc_id,'calculation_name':'AI_FORECAST',
                      'formula':'experimental_model_terminal_price; CAGR_price_only_elapsed_365.25; not_rankable',
                      'inputs':{'subject':iid,'run_id':self.run.run_id,'cutoff':cutoff.isoformat(),
                          'evidence_ids':list(refs),'source_sha256':extra.get('source_sha256'),
                          'origin':extra.get('origin'),'target':target.isoformat(),
                          'horizon_steps':60,'price_basis':'split-adjusted','ranking_allowed':False},
                      'result':{'subject':iid,'status':status,'point':point,'price_cagr':price_cagr,
                          'ranking_allowed':False,'terminal_price':point,'reason':reason,
                          'ensemble_id':eid,'model_run_ids':list(ids),'models':saved,
                          'assessment':assessment,'provenance':provenance,
                          'missing_inputs':[reason] if reason else []}}
                mids, ensemble_id = ForecastStore(self.run.database_path).save_bundle(
                    self.run.run_id, iid, tuple(persist_models.values()), combined, assessment,
                    calculation_factory=atomic_calc,
                    calculation_writer=lambda calc, con: self.run.add_calculation(**calc,_connection=con))
                model_rows = [{'model_id':m.model_id,'run_row_id':ref,'status':m.status,'point':m.point,
                               'error':m.error,'validation_level':m.validation_level} for m,ref in zip(persist_models.values(),mids)]
                extra.update({'model_statuses':model_rows,'ensemble_id':ensemble_id})
                persisted=True
            except Exception as exc:
                status='UNAVAILABLE';reason=type(exc).__name__+': '+str(exc)
                # Persistence failure never masquerades as successful forecast.
                point=None;ensemble_id=None;model_rows=[]
            cagr = None
            if point is not None and extra.get('actual_elapsed_years',0)>0:
                cagr = (point/extra['current_price'])**(1/extra['actual_elapsed_years'])-1
            output={'subject':iid,'status':status,'point':point,'price_cagr':cagr,
                    'ranking_allowed':False,'terminal_price':point,'reason':reason,
                    'ensemble_id':ensemble_id,'model_run_ids':[m['run_row_id'] for m in model_rows],
                    'models':model_rows,'assessment':assessment,'provenance':extra,
                    'missing_inputs':[reason] if reason else []}
            if not persisted:
                try:
                    self.run.add_calculation(calculation_id=calc_id,calculation_name='AI_FORECAST',
                        formula='experimental_model_terminal_price; CAGR_price_only_elapsed_365.25; not_rankable',
                        inputs={'subject':iid,'run_id':self.run.run_id,'cutoff':cutoff.isoformat(),
                            'evidence_ids':list(refs),'source_sha256':extra.get('source_sha256'),
                            'origin':extra.get('origin'),'target':extra.get('target'),
                            'horizon_steps':extra.get('horizon_steps'), 'price_basis':extra.get('price_basis'),
                            'ranking_allowed':False},result=output)
                except Exception as write_error:
                    missing.append(iid+':failed canonical calculation persistence:'+str(write_error))
                    calc_id=None
            if calc_id is not None:calculation_ids.append(calc_id)
            all_refs.extend(refs)
            if reason:missing.append(iid+':'+reason)
            results[iid] = output
            lines=[f'{iid}: AI 보조 전망 {status}; 투자 우선순위·적정가·기존 EPS 시나리오 변경 없음.',
                   f'실험적 AI 가격 CAGR(배당·세금·비용·환율 미포함): {cagr if cagr is not None else "확인 불가"}',
                   f'모델 포인트={[(x["model_id"],x["point"],x["status"]) for x in model_rows]}; 불일치·조건부 MC={assessment.get("model_disagreement_dispersion", "확인 불가")}/{assessment.get("status","UNAVAILABLE")}',
                   f'목표일={extra.get("target","확인 불가")}; 출처={list(refs)}; 저장앙상블={ensemble_id or "없음"}']
            if reason:lines.append('미확인: '+reason)
            sections.append(ReportSectionInput(name='ai_forecast_'+iid,title='실험적 AI 가격 전망 · '+iid,
                lines=tuple(lines),status=Availability.PARTIAL,evidence_ids=tuple(refs),
                calculation_ids=(calc_id,) if calc_id else (),metadata={'ranking_allowed':False,'experimental':True}))
        return ForecastIntegrationResult(tuple(sections),tuple(calculation_ids),tuple(dict.fromkeys(all_refs)),
                                         tuple(missing),results,tuple(dict.fromkeys(
                                           'AI_FORECAST_REVIEW:'+iid for iid,item in results.items()
                                           if item['status']=='PARTIAL' or (item['status']=='UNAVAILABLE' and item['reason'] and 'research' in item['reason']))))


def load_postvaluation_service(run, forecast_config: Path | None, forecast_inputs: Path | None = None, *, source_collector=None):
    if forecast_config is None:
        return None
    config = ForecastingConfig.from_file(forecast_config)
    # An inputs JSON only selects already persisted source IDs: no raw arrays.
    return PostValuationForecastService(run, config, input_selections=_selection_map(forecast_inputs), source_collector=source_collector)
