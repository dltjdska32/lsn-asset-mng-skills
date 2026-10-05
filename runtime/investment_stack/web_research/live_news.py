"""Generic news discovery, with issuer confirmation deliberately unclaimed."""
from datetime import datetime, timezone
from dataclasses import replace
from time import monotonic
from investment_stack.providers.health import BoundedProviderCalls, ProviderExecutionPolicy
import hashlib
import json
import re
from urllib.parse import urlencode, urlparse, urlsplit, urlunsplit, parse_qsl
from investment_stack.web_research.models import WebResearchHit, WebResearchIntent, WebResearchResponse


class LiveNewsBackend:
    def __init__(self, resolver, transport, preferred=None, *, previous_run_as_of=None,
                 seen_article_ids=(), seen_event_ids=(), policy=None):
        self.resolver, self.transport, self.preferred = resolver, transport, preferred
        self.cache = {}
        self.policy = policy or ProviderExecutionPolicy(attempt_timeout_seconds=10, total_timeout_seconds=30)
        self.health = BoundedProviderCalls()
        self.attempts = []
        self.set_context(previous_run_as_of=previous_run_as_of,
                         seen_article_ids=seen_article_ids, seen_event_ids=seen_event_ids)

    def set_context(self, *, previous_run_as_of=None, seen_article_ids=(), seen_event_ids=()):
        self.previous_run_as_of = self._timestamp(previous_run_as_of) if previous_run_as_of else None
        self.seen_article_ids = frozenset(seen_article_ids)
        self.seen_event_ids = frozenset(seen_event_ids)
        self.cache.clear()

    @staticmethod
    def _timestamp(value):
        stamp = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            raise ValueError('news timestamps require an explicit timezone')
        return stamp.astimezone(timezone.utc)

    @staticmethod
    def article_id(url):
        parts = urlsplit(url)
        query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query)
                                 if not k.lower().startswith('utm_') and k.lower() not in {'gclid', 'fbclid'}))
        canonical = urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, query, ''))
        return hashlib.sha256(canonical.encode()).hexdigest()

    def _filter(self, response, iid, analysis_as_of):
        upper = self._timestamp(analysis_as_of)
        if self.previous_run_as_of is not None and self.previous_run_as_of > upper:
            raise ValueError('previous news cutoff must not exceed analysis_as_of')
        articles, events, titles, hits = set(self.seen_article_ids), set(self.seen_event_ids), set(), []
        for hit in response.hits:
            try:
                published = self._timestamp(hit.published_at)
                parsed_url = urlparse(hit.source_url)
                if parsed_url.scheme != 'https' or not parsed_url.netloc:
                    continue
            except (ValueError, TypeError):
                continue
            if published > upper or (self.previous_run_as_of is not None and published <= self.previous_run_as_of):
                continue
            if hit.metadata.get('instrument_id') != iid:
                continue
            aid = self.article_id(hit.source_url)
            eid = hit.event_cluster_id or hit.metadata.get('event_cluster_id')
            title = re.sub(r'\W+', ' ', hit.title.casefold()).strip()
            if aid in articles or (eid and eid in events) or title in titles:
                continue
            articles.add(aid); titles.add(title)
            if eid:
                events.add(eid)
            metadata = dict(hit.metadata)
            if metadata.get('material_event') is True and not (
                metadata.get('article_content_verified') is True and metadata.get('independent_verification') is True
            ):
                metadata.update(material_event=False, potential_material_event=True,
                    materiality_basis='reported event requires content and independent verification')
            hits.append(replace(hit, metadata={**metadata, 'article_id': aid,
                'news_cutoff': self.previous_run_as_of.isoformat() if self.previous_run_as_of else None,
                'news_window_end': upper.isoformat()}))
        return WebResearchResponse(response.intent, tuple(hits))

    def _bounded(self, key, operation, deadline):
        blocked = self.health.blocked_reason(key)
        if blocked:
            self.attempts.append({'provider': key[0], 'status': 'SKIPPED', 'reason': blocked})
            return None
        for attempt in range(self.policy.max_retries + 1):
            remaining = deadline - monotonic()
            if remaining <= 0:
                self.attempts.append({'provider': key[0], 'status': 'BUDGET_EXHAUSTED'})
                return None
            try:
                value = self.health.call(key, operation, min(remaining, self.policy.attempt_timeout_seconds))
                self.health.mark_healthy(key)
                self.attempts.append({'provider': key[0], 'status': 'AVAILABLE', 'attempt_number': attempt + 1})
                return value
            except Exception as exc:
                self.attempts.append({'provider': key[0], 'status': 'TIMEOUT' if isinstance(exc, TimeoutError) else 'ERROR',
                                      'attempt_number': attempt + 1, 'error_type': type(exc).__name__})
                if self.health.blocked_reason(key):
                    break
        self.health.mark_failed(key, self.policy.cooldown_seconds)
        return None

    def __call__(self, intent, query, analysis_as_of):
        if intent is not WebResearchIntent.LATEST_RELEVANT_NEWS:
            if self.preferred is not None:
                response = self._bounded(('preferred', intent), lambda: self.preferred(intent, query, analysis_as_of),
                                         monotonic() + self.policy.total_timeout_seconds)
                if isinstance(response, WebResearchResponse):
                    return response
            return WebResearchResponse(intent, ())
        iid = next((iid for iid in self.resolver.resolved if query.startswith(iid+' ')), None)
        if iid is None:
            return WebResearchResponse(intent, ())
        cache_key = (iid, analysis_as_of)
        if cache_key in self.cache:
            return self.cache[cache_key]
        # Validate the pinned window even if the source returns no articles.
        self._filter(WebResearchResponse(intent, ()), iid, analysis_as_of)
        deadline = monotonic() + self.policy.total_timeout_seconds
        if self.preferred is not None:
            response = self._bounded(('preferred', intent), lambda: self.preferred(intent, query, analysis_as_of), deadline)
            if isinstance(response, WebResearchResponse):
                response = self._filter(response, iid, analysis_as_of)
                if response.hits:
                    self.cache[cache_key] = response
                    return response
        asset = self.resolver.resolved[iid]
        ticker = asset.ticker + ('.T' if asset.exchange == 'JPX' else '.KS' if asset.exchange == 'KRX' else '')
        hits = []
        for host in ('query1.finance.yahoo.com','query2.finance.yahoo.com'):
            url = f'https://{host}/v1/finance/search?' + urlencode({'q':ticker,'quotesCount':0,'newsCount':10})
            try:
                raw = self._bounded((host, intent), lambda url=url: self.transport(url, {'User-Agent':'Mozilla/5.0'}, 10), deadline)
                if raw is None:
                    continue
                data = json.loads(raw)
                retrieved = self.transport.retrieved_at_for(url) if hasattr(self.transport,'retrieved_at_for') else datetime.now(timezone.utc).isoformat()
                for news in data.get('news', []):
                    # Search relevance alone is not an instrument binding.
                    related = {str(t).upper() for t in news.get('relatedTickers', [])}
                    if ticker.upper() not in related:
                        continue
                    link = news.get('link',''); title = news.get('title',''); stamp = news.get('providerPublishTime')
                    if urlparse(link).scheme != 'https' or not title or isinstance(stamp,bool) or not isinstance(stamp,int):
                        continue
                    published = datetime.fromtimestamp(stamp,timezone.utc).isoformat()
                    candidate = bool(re.search(r'contract|acqui[rs]|merger|earnings|guidance|investigation|lawsuit|bankrupt|계약|실적|인수|합병|소송',title,re.I))
                    hits.append(WebResearchHit(str(news.get('publisher') or 'Unknown publisher'),link,title,
                        published_at=published,retrieved_at=retrieved,source_tier=3,
                        source_kind='news_article',official_confirmation_status='NEWS_REPORTED',
                        metadata={'instrument_id':iid,'related_tickers':sorted(related),
                            'discovery_source':url,'discovery_sha256':hashlib.sha256(raw).hexdigest(),
                            'headline_only':True,'article_content_verified':False,
                            'independent_verification':False,'material_event':False,
                            'potential_material_event':candidate,
                            'materiality_basis':'potential event headline screening; requires deep verification',
                            'calculation_input_approved':False}))
                hits = list(self._filter(WebResearchResponse(intent, tuple(hits)), iid, analysis_as_of).hits)
                if hits:
                    break
            except Exception:
                continue
        response = self._filter(WebResearchResponse(intent,tuple(hits)), iid, analysis_as_of)
        self.cache[cache_key] = response
        return response
