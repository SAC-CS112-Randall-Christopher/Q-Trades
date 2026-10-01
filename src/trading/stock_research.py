"""Bounded first-party stock evidence and read-only studies; no equity execution."""

import hashlib
import ipaddress
import json
import re
import socket
import threading
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field

from trading.experiment_registry import ExperimentRegistry, fingerprint
from trading.research_storage import ResearchStorage, load_plan

SEC = "https://data.sec.gov"
TICKERS = "https://www.sec.gov/files/company_tickers.json"
DEMO = "https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&symbol=IBM&apikey=demo"
USER_AGENT = "Q-Trades/CP21 https://github.com/SAC-CS112-Randall-Christopher/Q-Trades/issues/28"
MAX_SOURCE = 16 * 1024**2
GATE = threading.Lock()
LAST_REQUEST = 0.0
COOLDOWN: dict[str, float] = {}
TAGS = (
    "Assets",
    "Liabilities",
    "StockholdersEquity",
    "NetIncomeLoss",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
)


class StockQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    security: str = Field(pattern=r"^[A-Z0-9.-]{1,20}$")
    as_of: float = Field(gt=0)
    hypothesis: str = Field(min_length=12, max_length=500)
    market: bool = False


def public_url(url: str) -> str:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.port not in (None, 443)
        or parsed.username
        or parsed.password
        or parsed.fragment
        or parsed.hostname not in {"www.sec.gov", "data.sec.gov", "www.alphavantage.co"}
    ):
        raise ValueError("Only declared official HTTPS sources are permitted")
    if parsed.hostname == "www.alphavantage.co" and url != DEMO:
        raise ValueError("Only the published IBM daily demonstration endpoint is declared")
    if parsed.hostname == "data.sec.gov" and not re.fullmatch(
        r"/(submissions/CIK\d{10}(?:-submissions-\d{3})?\.json|api/xbrl/companyfacts/CIK\d{10}\.json)",
        parsed.path,
    ):
        raise ValueError("Undeclared SEC API path")
    if parsed.hostname == "www.sec.gov" and not (
        url == TICKERS
        or re.fullmatch(r"/Archives/edgar/data/\d+/\d{18}/[A-Za-z0-9_.-]+", parsed.path)
    ):
        raise ValueError("Undeclared filing source path")
    for address in socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM):
        if not ipaddress.ip_address(address[4][0]).is_global:
            raise ValueError("Official source resolved to a nonpublic address")
    return url


def fetch_public(url: str, user_agent: str = USER_AGENT) -> dict[str, Any]:
    global LAST_REQUEST
    public_url(url)
    # One process-wide gate across all SEC/provider instances, under the 10/s SEC ceiling.
    with GATE:
        bucket = (
            "SEC" if urlsplit(url).hostname in {"www.sec.gov", "data.sec.gov"} else "Alpha Vantage"
        )
        if time.monotonic() < COOLDOWN.get(bucket, 0):
            raise ValueError("Official source cooldown is active; cached research remains usable")
        wait = max(0.0, LAST_REQUEST + 0.5 - time.monotonic())
        if wait:
            time.sleep(wait)
        LAST_REQUEST = time.monotonic()
        with httpx.Client(timeout=15, trust_env=False, follow_redirects=False) as client:
            with client.stream(
                "GET", url, headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}
            ) as response:
                if response.status_code in {403, 429}:
                    COOLDOWN[bucket] = time.monotonic() + 600
                    raise ValueError(
                        "Official source denied/rate-limited access; ten-minute cooldown"
                    )
                if 300 <= response.status_code < 400:
                    raise ValueError("Source redirects are not followed")
                response.raise_for_status()
                chunks, size = [], 0
                deadline = time.monotonic() + 30
                for chunk in response.iter_bytes():
                    if time.monotonic() > deadline:
                        raise ValueError("Official source exceeded its total receive allowance")
                    size += len(chunk)
                    if size > MAX_SOURCE:
                        raise ValueError(
                            "Source exceeds sixteen MiB; no partial source substituted"
                        )
                    chunks.append(chunk)
    payload = b"".join(chunks)
    return {
        "url": url,
        "retrieved_at": time.time(),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "text": payload.decode("utf-8"),
    }


def known_at(fact: dict[str, Any], accepted: dict[str, str]) -> tuple[float, str]:
    timestamp = accepted.get(fact["accn"])
    if timestamp:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            return parsed.timestamp(), "accepted_timestamp"
    # Date-only facts never receive an invented intraday release time. Conservative
    # two-day boundary covers local filing dates; precision stays date-only.
    parsed = datetime.fromisoformat(fact["filed"]).replace(tzinfo=UTC) + timedelta(days=2)
    return parsed.timestamp(), "date_only_conservative_boundary"


def reported_facts(
    facts: dict[str, Any], submissions: dict[str, Any], cutoff: float
) -> list[dict[str, Any]]:
    recent = submissions["filings"]["recent"]
    accepted = dict(
        zip(recent["accessionNumber"], recent.get("acceptanceDateTime", []), strict=False)
    )
    results = []
    for tag in TAGS:
        definition = facts.get("facts", {}).get("us-gaap", {}).get(tag, {})
        versions: dict[tuple[Any, ...], dict[str, Any]] = {}
        for unit, rows in definition.get("units", {}).items():
            for fact in rows:
                if fact.get("form") not in {"10-K", "10-Q", "10-K/A", "10-Q/A"}:
                    continue
                available, precision = known_at(fact, accepted)
                if available > cutoff:
                    continue
                value = Decimal(str(fact["val"]))
                if not value.is_finite():
                    raise ValueError("Nonfinite source fact")
                key = (tag, unit, fact.get("start"), fact["end"])
                item = {
                    "tag": tag,
                    "label": definition.get("label", tag),
                    "unit": unit,
                    "value": str(value),
                    "start": fact.get("start"),
                    "end": fact["end"],
                    "accession": fact["accn"],
                    "form": fact["form"],
                    "filed": fact["filed"],
                    "known_at": available,
                    "availability_precision": precision,
                    "amendment": fact["form"].endswith("/A"),
                    "taxonomy": "us-gaap",
                }
                prior = versions.get(key)
                if not prior or (available, fact["accn"]) > (prior["known_at"], prior["accession"]):
                    versions[key] = item
                elif (available, fact["accn"]) == (
                    prior["known_at"],
                    prior["accession"],
                ) and prior != item:
                    raise ValueError("Ambiguous same-version reported fact")
        # At most two latest comparable periods PER declared tag, with explicit coverage.
        selected = sorted(versions.values(), key=lambda f: (f["end"], f["known_at"]), reverse=True)
        results.extend(selected[:2])
    return results


def ratios(rows: list[dict[str, Any]]) -> dict[str, Any]:
    assets = next(
        (r for r in rows if r["tag"] == "Assets" and r["unit"] == "USD" and r["start"] is None),
        None,
    )
    liabilities = next(
        (
            r
            for r in rows
            if r["tag"] == "Liabilities"
            and assets
            and r["unit"] == assets["unit"]
            and r["end"] == assets["end"]
            and r["start"] is None
            and r["accession"] == assets["accession"]
        ),
        None,
    )
    value = (
        str(Decimal(liabilities["value"]) / Decimal(assets["value"]))
        if assets and liabilities and Decimal(assets["value"]) != 0
        else None
    )
    return {
        "liabilities_to_assets": value,
        "units": "ratio",
        "basis": "Same instant/USD/accession",
        "reason": None if value is not None else "Compatible nonzero instant inputs unavailable",
        "consensus": None,
        "earnings_surprise": None,
    }


def market_summary(payload: dict[str, Any], cutoff: float) -> dict[str, Any]:
    metadata = payload.get("Meta Data", {})
    if metadata.get("2. Symbol") != "IBM" or metadata.get("5. Time Zone") not in {
        "US/Eastern",
        "America/New_York",
    }:
        raise ValueError("Published demonstration identity/timezone mismatch")
    series = payload.get("Time Series (Daily)")
    if not isinstance(series, dict) or not 2 <= len(series) <= 100:
        raise ValueError("Declared compact daily coverage unavailable")
    rows = []
    for day, values in sorted(series.items()):
        available = (
            datetime.fromisoformat(day).replace(tzinfo=UTC) + timedelta(days=2)
        ).timestamp()
        if available > cutoff:
            continue
        prices = [Decimal(values[k]) for k in ("1. open", "2. high", "3. low", "4. close")]
        volume = Decimal(values["5. volume"])
        if not all(p.is_finite() and p > 0 for p in prices) or not volume.is_finite() or volume < 0:
            raise ValueError("Invalid daily price/volume")
        if not prices[2] <= min(prices[0], prices[3]) <= max(prices[0], prices[3]) <= prices[1]:
            raise ValueError("Inconsistent OHLC envelope")
        rows.append({"date": day, "close": str(prices[3]), "volume": str(volume)})
    if len(rows) < 2:
        raise ValueError("At least two conservatively available sessions required")
    closes = [Decimal(r["close"]) for r in rows]
    return {
        "provider": "Alpha Vantage",
        "mode": "official_public_IBM_demonstration",
        "basis": "raw daily OHLCV; price change only",
        "currency": "USD",
        "security": "IBM",
        "timezone": metadata["5. Time Zone"],
        "source_last_refreshed": metadata["3. Last Refreshed"],
        "sessions": len(rows),
        "first": rows[0],
        "last": rows[-1],
        "raw_price_change": str(closes[-1] / closes[0] - 1),
        "sma20": str(sum(closes[-20:]) / 20) if len(closes) >= 20 else None,
        "corporate_actions": "Not supplied; no total-return or adjusted-price claim",
        "feed_entitlement": "Public documented demonstration; no personal real-time feed verified",
        "point_in_time_vintage": False,
        "limitations": [
            "Current downloadable revision; historical as-seen vintage unavailable",
            "Only IBM; no point-in-time universe, delisting coverage or survivor test",
            "Holiday calendar and source venue aggregation unverified",
            "Price-only analysis is not executable equity, profit or filing causation",
        ],
    }


class SourceText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in {"script", "style"}:
            self.hidden += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


class StockResearch:
    def __init__(self, registry: ExperimentRegistry):
        self.registry = registry
        with registry.lock:
            registry.db.executescript("""
                CREATE TABLE IF NOT EXISTS stock_sources(
                    seq INTEGER PRIMARY KEY,url TEXT NOT NULL,sha TEXT NOT NULL,
                    retrieved REAL NOT NULL,manifest TEXT NOT NULL,UNIQUE(url,sha));
                CREATE INDEX IF NOT EXISTS stock_cache ON stock_sources(url,retrieved);
                CREATE TABLE IF NOT EXISTS stock_provider_cooldown(
                    provider TEXT PRIMARY KEY,next_at REAL NOT NULL,reason TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS stock_studies(
                    id TEXT PRIMARY KEY,created REAL NOT NULL,question TEXT NOT NULL,
                    body TEXT NOT NULL,sha TEXT NOT NULL);
                CREATE TRIGGER IF NOT EXISTS stock_study_frozen BEFORE UPDATE ON stock_studies
                  BEGIN SELECT RAISE(ABORT,'Read-only study is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS stock_study_retained BEFORE DELETE ON stock_studies
                  BEGIN SELECT RAISE(ABORT,'Study history is permanent'); END;
            """)

    def source(self, url: str) -> dict[str, Any]:
        public_url(url)
        provider = (
            "SEC" if urlsplit(url).hostname in {"www.sec.gov", "data.sec.gov"} else "Alpha Vantage"
        )
        with self.registry.lock:
            cached = self.registry.db.execute(
                "SELECT manifest FROM stock_sources WHERE url=? AND retrieved>? "
                "ORDER BY seq DESC LIMIT 1",
                (url, time.time() - 86400),
            ).fetchone()
            cooldown = self.registry.db.execute(
                "SELECT next_at FROM stock_provider_cooldown WHERE provider=?", (provider,)
            ).fetchone()
        plan = load_plan(self.registry.path.parent)
        if plan is None:
            raise ValueError("Configure the existing verified G: research tiers for stock evidence")
        store = ResearchStorage(plan)
        try:
            if cached:
                metadata: dict[str, Any] = json.loads(cached["manifest"])
                chunks = [store.reopen(r)["text"] for r in metadata["references"]]
                payload = "".join(chunks)
                if hashlib.sha256(payload.encode()).hexdigest() != metadata["sha256"]:
                    raise ValueError("Archived official source hash mismatch")
                return metadata | {"text": payload}
            if cooldown and cooldown[0] > time.time():
                raise ValueError("Recorded official-source cooldown remains active after restart")
            try:
                policy_path = self.registry.path.parent / "stock-source-policy.json"
                if policy_path.exists():
                    if policy_path.stat().st_size > 8192:
                        raise ValueError("Declared source identification exceeds its bound")
                    source_policy = json.loads(policy_path.read_text())
                    user_agent = source_policy.get("user_agent", "")
                    if (
                        set(source_policy) != {"user_agent"}
                        or not isinstance(user_agent, str)
                        or not 12 <= len(user_agent) <= 300
                        or "\n" in user_agent
                        or "\r" in user_agent
                    ):
                        raise ValueError("Declare a bounded identified SEC user agent")
                    fetched = fetch_public(url, user_agent)
                else:
                    fetched = fetch_public(url)
            except ValueError as exc:
                if "denied/rate-limited" in str(exc):
                    with self.registry.transaction():
                        self.registry.db.execute(
                            "INSERT INTO stock_provider_cooldown VALUES(?,?,?) "
                            "ON CONFLICT(provider) DO UPDATE SET next_at=excluded.next_at,"
                            "reason=excluded.reason",
                            (provider, time.time() + 600, str(exc)),
                        )
                raise
            references = []
            parts = [
                fetched["text"][i : i + 100000] for i in range(0, len(fetched["text"]), 100000)
            ]
            for start in range(0, len(parts), 8):
                batch = [
                    {
                        "kind": "stock_official_source",
                        "at": fetched["retrieved_at"],
                        "url": url,
                        "source_sha256": fetched["sha256"],
                        "part": start + i,
                        "parts": len(parts),
                        "text": part,
                        "protected_until": fetched["retrieved_at"] + 604800,
                    }
                    for i, part in enumerate(parts[start : start + 8])
                ]
                refs = store.append(batch, time.time())
                if any(
                    store.reopen(ref) != packet for ref, packet in zip(refs, batch, strict=True)
                ):
                    raise ValueError("Official source archive finalization failed")
                references.extend(refs)
            metadata = {k: v for k, v in fetched.items() if k != "text"} | {
                "references": references
            }
            with self.registry.transaction():
                self.registry.db.execute(
                    "INSERT OR IGNORE INTO stock_sources(url,sha,retrieved,manifest) "
                    "VALUES(?,?,?,?)",
                    (url, fetched["sha256"], fetched["retrieved_at"], json.dumps(metadata)),
                )
            return fetched | {"references": references}
        finally:
            store.close()

    def investigate(self, question: StockQuestion) -> dict[str, Any]:
        if question.as_of > time.time() + 1:
            raise ValueError("Future information cutoff is unsupported")
        tickers = None
        issuer: dict[str, Any]
        if question.security.isdigit() and 0 < int(question.security) < 10**10:
            issuer = {"cik_str": int(question.security), "ticker": None}
        else:
            tickers = self.source(TICKERS)
            candidates = [
                r for r in json.loads(tickers["text"]).values() if r["ticker"] == question.security
            ]
            if len(candidates) != 1:
                raise ValueError("Issuer ticker ambiguous/unavailable; specify its current SEC CIK")
            issuer = candidates[0]
        cik = f"{int(issuer['cik_str']):010d}"
        submissions_source = self.source(SEC + f"/submissions/CIK{cik}.json")
        facts_source = self.source(SEC + f"/api/xbrl/companyfacts/CIK{cik}.json")
        submissions, facts = (
            json.loads(submissions_source["text"]),
            json.loads(facts_source["text"], parse_float=Decimal),
        )
        if int(facts["cik"]) != int(cik) or int(submissions["cik"]) != int(cik):
            raise ValueError("Official source issuer identities differ")
        if issuer["ticker"] is None:
            issuer["ticker"] = ",".join(submissions.get("tickers", [])) or "unavailable"
        rows = reported_facts(facts, submissions, question.as_of)
        recent = submissions["filings"]["recent"]
        timeline = []
        for i, accession in enumerate(recent["accessionNumber"]):
            if recent["form"][i] not in {"10-K", "10-Q", "10-K/A", "10-Q/A"}:
                continue
            available, precision = known_at(
                {"accn": accession, "filed": recent["filingDate"][i]},
                {accession: recent["acceptanceDateTime"][i]},
            )
            if available > question.as_of:
                continue
            filename = recent["primaryDocument"][i]
            url = (
                f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
                f"{accession.replace('-', '')}/{filename}"
            )
            timeline.append(
                {
                    "accession": accession,
                    "form": recent["form"][i],
                    "period": recent["reportDate"][i],
                    "known_at": available,
                    "availability_precision": precision,
                    "source_url": url,
                }
            )
            if len(timeline) == 2:
                break
        sources = ([tickers] if tickers else []) + [submissions_source, facts_source]
        market: dict[str, Any] = {
            "status": "disconnected",
            "reason": "Public IBM example not requested; entitled feed unconfigured",
        }
        if question.market:
            if issuer["ticker"] != "IBM":
                market = {
                    "status": "unavailable",
                    "reason": "Only the documented public IBM demonstration is permitted",
                }
            else:
                try:
                    market_source = self.source(DEMO)
                    market = market_summary(json.loads(market_source["text"]), question.as_of)
                    sources.append(market_source)
                except (ValueError, httpx.HTTPError) as exc:
                    market = {"status": "unavailable", "reason": str(exc)[:300]}
        result = {
            "version": "stock-research-v1",
            "question": question.model_dump(),
            "identity": {
                "issuer": submissions["name"],
                "cik": cik,
                "ticker": issuer["ticker"],
                "instrument": "SEC issuer ticker; share class must be checked",
                "currency": "USD for displayed USD facts",
                "exchange": submissions.get("exchanges"),
                "session": "Daily research only; no intraday event/execution study",
                "timezone": "America/New_York for the IBM market demonstration",
                "mapping_known_at": (tickers or submissions_source)["retrieved_at"],
                "history": "Current mapping only; historical ticker/universe membership unverified",
            },
            "facts": rows,
            "fact_coverage": {
                "tags": list(TAGS),
                "periods_per_tag": 2,
                "omissions": (
                    "Declared standard US-GAAP tags/two latest periods only; "
                    "extensions and older periods not inspected"
                ),
            },
            "ratios": ratios(rows),
            "timeline": timeline,
            "market": market,
            "sources": [{k: v for k, v in s.items() if k != "text"} for s in sources],
            "executability": "Read-only research; no stock/broker/order capability",
            "macro": "No concrete vintage-macro hypothesis or configured entitlement",
            "limitations": [
                "Known accession versions; date-only availability cannot support minute claims",
                "Retrospective Companyfacts extraction; original filing inspection is separate",
                "No consensus estimates, surprise, causal attribution or trading edge inferred",
            ],
        }
        return self._save(question, result, sources)

    def _save(
        self, question: StockQuestion, result: dict[str, Any], sources: list[dict[str, Any]]
    ) -> dict[str, Any]:
        identity = (
            "stock-"
            + fingerprint(
                {"question": question.model_dump(), "sources": [s["sha256"] for s in sources]}
            )[:32]
        )
        result["id"] = identity
        encoded = json.dumps(result, sort_keys=True, allow_nan=False)
        if len(encoded.encode()) > 65536:
            raise ValueError("Bounded stock study result exceeded; exact sources remain archived")
        with self.registry.transaction():
            self.registry.db.execute(
                "INSERT OR IGNORE INTO stock_studies VALUES(?,?,?,?,?)",
                (
                    identity,
                    time.time(),
                    json.dumps(question.model_dump()),
                    encoded,
                    fingerprint(result),
                ),
            )
        return self.get(identity)

    def market_study(self, question: StockQuestion) -> dict[str, Any]:
        if question.security != "IBM" or not question.market or question.as_of > time.time() + 1:
            raise ValueError("Explicit public IBM daily-only study required")
        source = self.source(DEMO)
        summary = market_summary(json.loads(source["text"]), question.as_of)
        result = {
            "version": "stock-market-study-v1",
            "question": question.model_dump(),
            "identity": {
                "issuer": "IBM provider example; SEC issuer identity unverified",
                "cik": "unverified",
                "ticker": "IBM",
                "history": "Public demonstration only; no historical issuer mapping",
            },
            "facts": [],
            "ratios": {
                "liabilities_to_assets": None,
                "reason": "Filing inputs were not part of this price-only study",
            },
            "timeline": [],
            "market": summary,
            "sources": [{k: v for k, v in source.items() if k != "text"}],
            "executability": "Read-only public daily example; no stock execution",
            "limitations": summary["limitations"],
        }
        return self._save(question, result, [source])

    def get(self, identity: str) -> dict[str, Any]:
        with self.registry.transaction():
            row = self.registry.db.execute(
                "SELECT * FROM stock_studies WHERE id=?", (identity,)
            ).fetchone()
            if row is None:
                raise ValueError("Unknown read-only stock study")
            result: dict[str, Any] = json.loads(row["body"])
            if fingerprint(result) != row["sha"]:
                raise ValueError("Saved stock study hash mismatch")
            self.registry.db.execute(
                "INSERT OR IGNORE INTO evidence_windows VALUES(?,?,?,'stock research disclosure')",
                (identity, 0, row["created"]),
            )
        return result

    def section(self, identity: str, index: int, phrase: str) -> dict[str, Any]:
        result = self.get(identity)
        if index not in {0, 1} or index >= len(result["timeline"]) or not 3 <= len(phrase) <= 100:
            raise ValueError("Choose a declared filing and bounded exact section phrase")
        source = self.source(result["timeline"][index]["source_url"])
        parser = SourceText()
        parser.feed(source["text"])
        text = " ".join(" ".join(parser.parts).split())
        offsets = [m.start() for m in re.finditer(re.escape(phrase), text, re.IGNORECASE)]
        start = offsets[-1] if offsets else 0
        excerpt = text[start : start + 8000] if offsets else ""
        suspicious = bool(
            re.search(
                r"ignore (?:all |previous )?instructions|system prompt|"
                r"send (?:password|credentials)",
                excerpt,
                re.IGNORECASE,
            )
        )
        return {
            "accession": result["timeline"][index]["accession"],
            "phrase": phrase,
            "source": {k: v for k, v in source.items() if k != "text"},
            "offset": start,
            "matches": len(offsets),
            "excerpt": excerpt,
            "complete_section": False,
            "untrusted_instruction_detected": suspicious,
            "scope": "Bounded exact source excerpt, never role instructions",
        }

    def compare_filings(self, identity: str, phrase: str) -> dict[str, Any]:
        current, prior = self.section(identity, 0, phrase), self.section(identity, 1, phrase)
        a, b = set(current["excerpt"].split()), set(prior["excerpt"].split())
        return {
            "current": current,
            "prior": prior,
            "new_terms": sorted(a - b)[:30],
            "removed_terms": sorted(b - a)[:30],
            "complete_comparison": False,
            "scope": "Literal terms in bounded excerpts; no semantic/causal attribution",
        }
