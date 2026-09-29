# Q-Trades baseline code evidence

Original uploaded source; line numbers refer to the unchanged baseline. These excerpts establish source behavior, not production execution.

## Financial writer and durable transaction

`src/trading/paper_store.py:15–41`

```text
  15: SCHEMA = """
  16: CREATE TABLE IF NOT EXISTS paper_state (
  17:   id integer PRIMARY KEY CHECK (id = 1), revision bigint NOT NULL, body jsonb NOT NULL
  18: );
  19: CREATE TABLE IF NOT EXISTS paper_events (
  20:   id bigserial PRIMARY KEY, revision bigint NOT NULL, at double precision NOT NULL,
  21:   kind text NOT NULL, account text NOT NULL, body jsonb NOT NULL
  22: );
  23: CREATE INDEX IF NOT EXISTS paper_events_recent ON paper_events(account, id DESC);
  24: CREATE INDEX IF NOT EXISTS paper_events_kind ON paper_events(kind, id DESC);
  25: CREATE TABLE IF NOT EXISTS paper_journal (
  26:   event_id bigint NOT NULL REFERENCES paper_events(id), line_no integer NOT NULL,
  27:   account text NOT NULL, asset text NOT NULL, bucket text NOT NULL, amount numeric NOT NULL,
  28:   PRIMARY KEY(event_id, line_no)
  29: );
  30: CREATE TABLE IF NOT EXISTS paper_bars (
  31:   symbol text NOT NULL, open_ms bigint NOT NULL, observed_at double precision NOT NULL,
  32:   bootstrap boolean NOT NULL, body jsonb NOT NULL, PRIMARY KEY(symbol, open_ms)
  33: );
  34: CREATE OR REPLACE FUNCTION paper_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
  35: BEGIN RAISE EXCEPTION 'Paper audit records are append-only'; END; $$;
  36: CREATE OR REPLACE TRIGGER paper_events_immutable BEFORE UPDATE OR DELETE ON paper_events
  37: FOR EACH ROW EXECUTE FUNCTION paper_immutable();
  38: CREATE OR REPLACE TRIGGER paper_journal_immutable BEFORE UPDATE OR DELETE ON paper_journal
  39: FOR EACH ROW EXECUTE FUNCTION paper_immutable();
  40: CREATE OR REPLACE TRIGGER paper_bars_immutable BEFORE UPDATE OR DELETE ON paper_bars
  41: FOR EACH ROW EXECUTE FUNCTION paper_immutable();
```

## Exclusive ownership and atomic commit

`src/trading/paper_store.py:53–131`

```text
  53: class PaperStore:
  54:     def __init__(self, dsn: str, *, owner: bool = False):
  55:         self.owner = owner
  56:         self.connection = psycopg.connect(dsn, autocommit=True, row_factory=dict_row)
  57:         self.connection.execute("SET statement_timeout = '5s'")
  58:         self.connection.execute("SET lock_timeout = '3s'")
  59:         if owner:
  60:             # Session lock also distinguishes test schemas on the same database.
  61:             row = self.connection.execute(
  62:                 "SELECT pg_try_advisory_lock(hashtext(current_database() || current_schema()), "
  63:                 "734921) AS acquired"
  64:             ).fetchone()
  65:             if not row or not row["acquired"]:
  66:                 self.connection.close()
  67:                 raise RuntimeError("Another paper engine owns this database")
  68:         if owner:
  69:             self.connection.execute(SCHEMA)
  70: 
  71:     def require_owner(self) -> None:
  72:         if not self.owner:
  73:             raise RuntimeError("Financial mutation requires the exclusive engine writer lock")
  74: 
  75:     def close(self) -> None:
  76:         self.connection.close()
  77: 
  78:     def initialize(self, now: float) -> None:
  79:         self.require_owner()
  80:         with self.connection.transaction():
  81:             inserted = self.connection.execute(
  82:                 "INSERT INTO paper_state VALUES (1, 0, %s) ON CONFLICT DO NOTHING RETURNING id",
  83:                 (Jsonb(initial_state(now)),),
  84:             ).fetchone()
  85:             if inserted:
  86:                 engine = PaperEngine(initial_state(now), now)
  87:                 engine.seed()
  88:                 self._append(engine, 0)
  89: 
  90:     def _append(self, engine: PaperEngine, revision: int) -> None:
  91:         for event in engine.events:
  92:             row = self.connection.execute(
  93:                 "INSERT INTO paper_events(revision, at, kind, account, body) "
  94:                 "VALUES (%s,%s,%s,%s,%s) RETURNING id",
  95:                 (revision, event["at"], event["kind"], event["account"], Jsonb(event["body"])),
  96:             ).fetchone()
  97:             assert row is not None
  98:             for index, line in enumerate(event["lines"]):
  99:                 self.connection.execute(
 100:                     "INSERT INTO paper_journal VALUES (%s,%s,%s,%s,%s,%s)",
 101:                     (
 102:                         row["id"],
 103:                         index,
 104:                         event["account"],
 105:                         line["asset"],
 106:                         line["bucket"],
 107:                         Decimal(line["amount"]),
 108:                     ),
 109:                 )
 110: 
 111:     def transact(self, now: float, work: Callable[[PaperEngine], None]) -> dict[str, Any]:
 112:         self.require_owner()
 113:         with self.connection.transaction():
 114:             row = self.connection.execute(
 115:                 "SELECT * FROM paper_state WHERE id=1 FOR UPDATE"
 116:             ).fetchone()
 117:             if not row:
 118:                 raise RuntimeError("Paper account was not initialized")
 119:             state: dict[str, Any] = row["body"]
 120:             if state.get("schema") != 1:
 121:                 raise RuntimeError("Unsupported paper state version")
 122:             engine = PaperEngine(state, now)
 123:             work(engine)
 124:             engine.assert_invariants()
 125:             revision = row["revision"] + 1
 126:             self._append(engine, revision)
 127:             self.connection.execute(
 128:                 "UPDATE paper_state SET revision=%s, body=%s WHERE id=1",
 129:                 (revision, Jsonb(engine.state)),
 130:             )
 131:         return engine.state
```

## Model assumptions

`src/trading/paper_engine.py:9–15`

```text
   9: D = Decimal
  10: FEE = D("0.001")
  11: SLIPPAGE = D("0.0002")
  12: PARTICIPATION = D("0.10")
  13: REVIEW_SECONDS = 4 * 3600
  14: SYMBOLS = ("BTCUSD", "ETHUSD")
  15: MODEL_VERSION = "paper-rest-ioc-v1"
```

## Account valuation and fill permissions

`src/trading/paper_engine.py:280–350`

```text
 280:     def value(self, a: dict[str, Any], frames: dict[str, dict[str, Any]]) -> bool:
 281:         equity = D(a["cash"])
 282:         for symbol, pos in a["positions"].items():
 283:             frame = frames.get(symbol)
 284:             if not frame or self.now - frame["observed"] > 5:
 285:                 a["valuation_fresh"] = False
 286:                 return False
 287:             book: Book = frame["book"]
 288:             rules = frame["rules"]
 289:             qty = D(pos["quantity"])
 290:             filled, gross = walk_book(book, "sell", qty, D(0), rules)
 291:             if filled < qty or qty < rules["min_qty"] or gross < rules["min_notional"]:
 292:                 a["valuation_fresh"] = False
 293:                 return False  # No complete executable valuation for missing depth or dust.
 294:             equity += gross * (1 - FEE)
 295:         a["equity"] = str(equity)
 296:         a["valuation_fresh"] = True
 297:         a["risk_peak"] = str(max(D(a["risk_peak"]), equity))
 298:         nav = equity / D(a["units"])
 299:         peak = max(D(a["nav_peak"]), nav)
 300:         a["nav_peak"] = str(peak)
 301:         a["max_drawdown"] = str(max(D(a["max_drawdown"]), 1 - nav / peak))
 302:         if equity <= D(a["risk_peak"]) * D("0.65"):
 303:             a["drawdown_pause"] = True
 304:         if int(self.now // 86400) != a["day"]:
 305:             a.update(
 306:                 day=int(self.now // 86400),
 307:                 day_start=str(equity),
 308:                 day_turnover="0",
 309:                 daily_pause=False,
 310:             )
 311:         if equity <= D(a["day_start"]) * D("0.85"):
 312:             a["daily_pause"] = True
 313:         return True
 314: 
 315:     def fill(self, name: str, a: dict[str, Any], symbol: str, frame: dict[str, Any]) -> None:
 316:         order = a["pending"][symbol]
 317:         if self.now < order["created_at"] + 1 or frame["observed"] <= order["created_at"]:
 318:             return
 319:         if order["side"] == "buy" and (
 320:             self.state["paused"]
 321:             or not frame.get("entry_allowed", True)
 322:             or a["daily_pause"]
 323:             or a["drawdown_pause"]
 324:             or a["failure_pending"]
 325:             or self.now < a["cooldown_until"]
 326:         ):
 327:             self.cancel(name, a, symbol, "Entry permission revoked")
 328:             return
 329:         if self.now - order["created_at"] > 15:
 330:             self.cancel(name, a, symbol, "IOC observation window expired; no retrospective fill")
 331:             return
 332:         rules = frame["rules"]
 333:         qty = D(order["quantity"])
 334:         if qty != floor_step(qty, rules["step"]) or not rules["min_qty"] <= qty <= rules["max_qty"]:
 335:             self.cancel(name, a, symbol, "Quantity filters changed")
 336:             return
 337:         price_limit = D(order["limit"])
 338:         if (
 339:             price_limit != floor_step(price_limit, rules["tick"])
 340:             or qty * price_limit < rules["min_notional"]
 341:             or not rules["min_price"] <= price_limit <= rules["max_price"]
 342:         ):
 343:             self.cancel(name, a, symbol, "Price or notional filters changed")
 344:             return
 345:         if frame["book"].update_id <= a["last_fill_sequence"].get(symbol, -1):
 346:             return  # Do not repeatedly consume unchanged displayed liquidity.
 347:         filled, gross = walk_book(frame["book"], order["side"], qty, price_limit, rules)
 348:         if filled <= 0:
 349:             self.cancel(name, a, symbol, "No displayed liquidity inside the price cap")
 350:             return
```

## Scoring and risk re-arm

`src/trading/paper_engine.py:665–737`

```text
 665:     def review(self) -> None:
 666:         """Two nonoverlapping, fully observed windows; frozen challengers and no forced changes."""
 667:         windows: list[dict[str, Any]] = []
 668:         enough_time = self.now - self.state["last_promotion"] >= 2 * REVIEW_SECONDS
 669:         for start, end in (
 670:             (self.now - 2 * REVIEW_SECONDS, self.now - REVIEW_SECONDS),
 671:             (self.now - REVIEW_SECONDS, self.now),
 672:         ):
 673:             scores = {}
 674:             for version in VARIANTS:
 675:                 a = self.state["accounts"][version]
 676:                 trades = [
 677:                     t
 678:                     for t in a["recent_trades"]
 679:                     if t["opened_at"] >= start and t["closed_at"] < end
 680:                 ]
 681:                 pnl = sum((D(t["pnl"]) for t in trades), D(0))
 682:                 costs = sum((D(t["fees"]) for t in trades), D(0))
 683:                 # Stress assumes one additional round-trip fee burden.
 684:                 returns = [D(t["pnl"]) / D(t["cost"]) for t in trades]
 685:                 scores[version] = {
 686:                     "trades": len(trades),
 687:                     "wins": sum(D(t["pnl"]) > 0 for t in trades),
 688:                     "net_pnl": str(pnl),
 689:                     "stress_pnl": str(pnl - costs),
 690:                     "mean_return": str(sum(returns, D(0)) / len(returns)) if returns else "0",
 691:                     "max_drawdown": a["max_drawdown"],
 692:                 }
 693:             windows.append({"start": start, "end": end, "scores": scores})
 694:         primary = self.state["accounts"]["primary"]
 695:         incumbent = primary["version"]
 696:         candidates = []
 697:         for version in VARIANTS:
 698:             if version == incumbent:
 699:                 continue
 700:             gates = []
 701:             for window in windows:
 702:                 score = window["scores"][version]
 703:                 base = window["scores"][incumbent]
 704:                 gates.append(
 705:                     score["trades"] >= 10
 706:                     and base["trades"] >= 10
 707:                     and D(score["stress_pnl"]) > 0
 708:                     and D(score["mean_return"]) > D(base["mean_return"]) + D("0.001")
 709:                     and D(score["max_drawdown"]) <= min(D("0.35"), D(base["max_drawdown"]))
 710:                 )
 711:             if enough_time and all(gates):
 712:                 candidates.append(version)
 713:         selected = incumbent
 714:         reason = "Insufficient forward evidence or no challenger passed all gates; retain version"
 715:         if candidates and not primary["positions"] and not primary["pending"]:
 716:             selected = max(
 717:                 candidates,
 718:                 key=lambda v: sum((D(w["scores"][v]["mean_return"]) for w in windows), D(0)),
 719:             )
 720:             primary["version"] = selected
 721:             self.state["last_promotion"] = self.now
 722:             self.state["promotion_count"] += 1
 723:             reason = "Challenger passed two forward windows; paper-only promotion while flat"
 724:         risk_resumed = []
 725:         for name, a in self.state["accounts"].items():
 726:             if a["drawdown_pause"] and a["valuation_fresh"] and not a["failure_pending"]:
 727:                 risk_resumed.append(
 728:                     {
 729:                         "account": name,
 730:                         "old_peak": a["risk_peak"],
 731:                         "new_peak": a["equity"],
 732:                         "lifetime_dd": a["max_drawdown"],
 733:                     }
 734:                 )
 735:                 a["risk_peak"] = a["equity"]
 736:                 a["drawdown_pause"] = False
 737:                 a["cooldown_until"] = max(a["cooldown_until"], self.now + 600)
```

## Tick ordering

`src/trading/paper_engine.py:789–842`

```text
 789:         self.state["last_tick"] = self.now
 790:         self.state["features"] = study
 791:         for name, a in self.state["accounts"].items():
 792:             self.value(a, frames)
 793:             for symbol in list(a["pending"]):
 794:                 frame = frames.get(symbol)
 795:                 if self.now - a["pending"][symbol]["created_at"] > 15:
 796:                     self.cancel(name, a, symbol, "Expired across data gap or restart")
 797:                 elif frame and self.now - frame["observed"] <= 5:
 798:                     self.fill(name, a, symbol, frame)
 799:             fresh = self.value(a, frames)
 800:             if fresh and D(a["equity"]) < 5:
 801:                 a["failure_pending"] = True
 802:                 for symbol, order in list(a["pending"].items()):
 803:                     if order["side"] == "buy":
 804:                         self.cancel(name, a, symbol, "Account failure; entry cancelled")
 805:             if fresh and D(a["equity"]) >= 1000 and a["attempt"]["outcome"] == "open":
 806:                 a["attempt"]["outcome"] = "won"
 807:                 a["attempt"]["ended_at"] = self.now
 808:                 a["attempt_wins"] += 1
 809:                 self.emit(
 810:                     "attempt_won", name, {**a["attempt"], "equity": a["equity"], "target": "1000"}
 811:                 )
 812:             for symbol in list(a["positions"]):
 813:                 frame = frames.get(symbol)
 814:                 if frame and self.now - frame["observed"] <= 5:
 815:                     feature = study.get(symbol, {}).get(a["positions"][symbol]["version"], {})
 816:                     self.exit_position(name, a, symbol, frame, feature)
 817:             if a["failure_pending"]:
 818:                 self.failure_review(name, a)
 819:             if not fresh:
 820:                 continue
 821:             for symbol in a.get("symbols", SYMBOLS):
 822:                 frame = frames.get(symbol)
 823:                 feature = study.get(symbol, {}).get(a["version"])
 824:                 if not frame or not feature or self.now - frame["observed"] > 5:
 825:                     continue
 826:                 bar_id = feature.get("bar_open_ms")
 827:                 if bar_id is None or a["last_decision"].get(symbol, {}).get("bar") == bar_id:
 828:                     continue
 829:                 reason = self.enter(name, a, symbol, frame, feature)
 830:                 decision = {
 831:                     "symbol": symbol,
 832:                     "bar": bar_id,
 833:                     "at": self.now,
 834:                     "version": a["version"],
 835:                     "reason": reason,
 836:                     "features": feature,
 837:                 }
 838:                 a["last_decision"][symbol] = decision
 839:                 self.emit("decision", name, decision)
 840:         if self.now >= self.state["next_review"]:
 841:             self.review()
 842:         minute = int(self.now // 60)
```

## Existing strategy family

`src/trading/paper_strategy.py:1–16`

```text
   1: """Frozen candidates and closed-bar features. No fitting to future observations."""
   2: 
   3: from dataclasses import dataclass
   4: from decimal import Decimal
   5: from statistics import median
   6: from typing import Any
   7: 
   8: from trading.market import InvalidMarketData, decimal_string
   9: 
  10: D = Decimal
  11: VARIANTS: dict[str, dict[str, Any]] = {
  12:     "breakout-v1": {"lookback": 10, "volume_multiple": "2", "stop_atr": "1.5"},
  13:     "responsive-v1": {"lookback": 7, "volume_multiple": "1.5", "stop_atr": "1.5"},
  14:     "selective-v1": {"lookback": 15, "volume_multiple": "2.5", "stop_atr": "1.5"},
  15: }
  16: 
```

## Numerical split and holdout parameter

`src/trading/research_experiment.py:130–207`

```text
 130: def run_experiment(
 131:     rows: list[dict[str, Any]],
 132:     feature: str,
 133:     horizon: int,
 134:     prior_test_end: float = 0,
 135: ) -> dict[str, Any]:
 136:     data_hash = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
 137:     built = examples(rows, feature, horizon)
 138:     samples = built["samples"]
 139:     report: dict[str, Any] = {
 140:         "version": EXPERIMENT_VERSION,
 141:         "dataset_sha256": data_hash,
 142:         "feature": feature,
 143:         "horizon_minutes": horizon,
 144:         "symbol": "BTCUSD",
 145:         "samples": len(samples),
 146:         "excluded": built["excluded"],
 147:         "cost_version": "quote-cost-v1-0.10pct-per-side-2bps-adverse",
 148:         "limitations": [
 149:             "Historical observed quote labels; no simulated fills or account returns.",
 150:             "Minute samples cannot establish intraminute execution or queue position.",
 151:             "Overlapping labels and a short market history limit independent evidence.",
 152:             "One fixed ridge coefficient penalty; no hyperparameter search or primary promotion.",
 153:         ],
 154:     }
 155:     if len(samples) < 300:
 156:         return dict(report, status="insufficient_data", reason="Fewer than 300 matured examples")
 157:     split_at = max(samples[int(len(samples) * 0.7)]["at"], prior_test_end + horizon * 60 + 1)
 158:     train = [s for s in samples if s["label_available_at"] < split_at - horizon * 60]
 159:     test = [s for s in samples if s["at"] >= split_at]
 160:     report.update(train_samples=len(train), test_samples=len(test), split_at=split_at)
 161:     if len(train) < 200 or len(test) < 50:
 162:         return dict(
 163:             report,
 164:             status="insufficient_data",
 165:             reason="Need 200 training and 50 new purged test examples",
 166:         )
 167:     x_mean = statistics.mean(s["x"] for s in train)
 168:     x_scale = statistics.pstdev(s["x"] for s in train) or 1.0
 169:     y_mean = statistics.mean(s["y"] for s in train)
 170:     cross = sum(((s["x"] - x_mean) / x_scale) * (s["y"] - y_mean) for s in train)
 171:     squares = sum(((s["x"] - x_mean) / x_scale) ** 2 for s in train)
 172:     weight = cross / (squares + 1.0)
 173:     predictions = [y_mean + weight * (s["x"] - x_mean) / x_scale for s in test]
 174:     mse = statistics.mean((p - s["y"]) ** 2 for p, s in zip(predictions, test, strict=True))
 175:     baseline_mse = statistics.mean((y_mean - s["y"]) ** 2 for s in test)
 176:     selected = [s for p, s in zip(predictions, test, strict=True) if p > 0]
 177:     report.update(
 178:         status="completed",
 179:         test_start=test[0]["at"],
 180:         test_end=max(s["end_at"] for s in test),
 181:         train_end=max(s["label_available_at"] for s in train),
 182:         model={
 183:             "x_mean": x_mean,
 184:             "x_scale": x_scale,
 185:             "intercept": y_mean,
 186:             "weight": weight,
 187:             "ridge_penalty": 1.0,
 188:         },
 189:         metrics={
 190:             "model_mse_bps_squared": format(mse, ".8f"),
 191:             "baseline_mse_bps_squared": format(baseline_mse, ".8f"),
 192:             "mse_improvement_percent": format((1 - mse / baseline_mse) * 100, ".6f")
 193:             if baseline_mse
 194:             else "0",
 195:             "positive_predictions": len(selected),
 196:             "selected_mean_net_bps": format(statistics.mean(s["y"] for s in selected), ".8f")
 197:             if selected
 198:             else None,
 199:         },
 200:         eligible_for_forward_review=bool(
 201:             mse < baseline_mse
 202:             and len(selected) >= 30
 203:             and statistics.mean(s["y"] for s in selected) > 0
 204:         ),
 205:         primary_changed=False,
 206:     )
 207:     return report
```

## Snapshot replay is not financial backtesting

`src/trading/replay.py:1–46`

```text
   1: """Recompute public snapshot metrics offline; no synthetic or financial results."""
   2: 
   3: from typing import Any
   4: 
   5: from trading.market import Book, InvalidMarketData, parse_book
   6: 
   7: 
   8: def replay_capture(capture: dict[str, Any]) -> dict[str, Any]:
   9:     if capture.get("schema_version") != 1 or capture.get("source") != "binance_us_public_rest":
  10:         raise ValueError("Unsupported capture format")
  11:     observations = capture.get("observations")
  12:     if not isinstance(observations, list) or len(observations) > 10000:
  13:         raise ValueError("Capture exceeds the bounded replay format")
  14:     valid = 0
  15:     rejected = []
  16:     latest = {}
  17:     prior_books: dict[str, Book] = {}
  18:     for record in observations:
  19:         if record.get("kind") != "depth":
  20:             continue
  21:         symbol = record.get("symbol")
  22:         if not isinstance(symbol, str):
  23:             raise ValueError("Capture has a depth record without a symbol")
  24:         try:
  25:             book = parse_book(record["payload"])
  26:             prior = prior_books.get(symbol)
  27:             if prior and (
  28:                 book.update_id < prior.update_id
  29:                 or (book.update_id == prior.update_id and book != prior)
  30:             ):
  31:                 raise InvalidMarketData("Sequence regression or inconsistent duplicate")
  32:             prior_books[symbol] = book
  33:             latest[symbol] = book.metrics()
  34:             valid += 1
  35:         except (InvalidMarketData, KeyError) as exc:
  36:             rejected.append({"id": record.get("id"), "symbol": symbol, "reason": str(exc)})
  37:     return {
  38:         "evidence_type": "offline_public_snapshot_replay",
  39:         "valid_depth_observations": valid,
  40:         "rejected": rejected,
  41:         "latest_metrics": latest,
  42:         "retention": capture.get("retention"),
  43:         "limitation": (
  44:             "Sampled REST books do not prove continuous coverage, fills, or strategy returns"
  45:         ),
  46:     }
```
