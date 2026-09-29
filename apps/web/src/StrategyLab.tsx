import { memo, useState } from "react";
import { Check, Circle, FlaskConical } from "lucide-react";

type Variant = {
  version: string;
  rules: { lookback: number; volume_multiple: string; stop_atr: string };
  features: { close?: string; breakout?: string; ema20_5m?: string; volume_ratio?: string; atr?: string; reason?: string };
  checks: Record<"trend" | "breakout" | "volume" | "extension", boolean | null>;
  feature_closed_at: number | null;
  feature_fresh: boolean;
  account: { closed: number; net_pnl: string; fees: string; max_drawdown: string; valuation_fresh: boolean };
};
export type Experiments = {
  active_version: string;
  variants: Variant[];
  next_review: number;
  review_count: number;
  latest_review: { at: number; selected: string; reason: string; windows: { start: number; end: number; trades: Record<string, number> }[] } | null;
};

const names: Record<string, string> = {
  "breakout-v1": "Baseline breakout",
  "responsive-v1": "Faster trigger",
  "selective-v1": "Stricter confirmation",
};
const questions: Record<string, string> = {
  "breakout-v1": "Can a confirmed price breakout continue far enough to cover trading costs?",
  "responsive-v1": "Does entering on a shorter breakout window capture more of the move, or produce more false starts?",
  "selective-v1": "Does waiting for a stronger breakout and more volume reduce losing entries enough to justify fewer trades?",
};
const number = (v?: string, digits = 2) => v == null ? "—" : Number(v).toLocaleString("en-US", { maximumFractionDigits: digits });
const money = (v: string) => Number(v).toLocaleString("en-US", { style: "currency", currency: "USD" });
const when = (s: number) => new Date(s * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });

export const StrategyLab = memo(function StrategyLab({ data, symbol, unavailable }: { data: Experiments; symbol: string; unavailable: boolean }) {
  const [inspected, setInspected] = useState<string | null>(null);
  const selected = data.variants.find(v => v.version === (inspected ?? data.active_version)) ?? data.variants[0];
  if (!selected) return null;
  const f = selected.features;
  const current = selected.feature_fresh && !unavailable;
  const digits = Number(f.close ?? 0) < 1 ? 8 : 2;
  const signals = [
    { key: "trend" as const, name: "Moving-average trend", value: `EMA ${number(f.ema20_5m, digits)}`, rule: "Last 5-minute close above its rising 20-period EMA." },
    { key: "breakout" as const, name: "Breakout", value: `${number(f.close, digits)} / ${number(f.breakout, digits)}`, rule: `Minute close above the prior ${selected.rules.lookback}-minute high.` },
    { key: "volume" as const, name: "Volume confirmation", value: `${number(f.volume_ratio)}× / >${selected.rules.volume_multiple}×`, rule: "Current minute's volume versus the preceding window's median." },
    { key: "extension" as const, name: "Volatility & chase limit", value: `ATR ${number(f.atr, digits)}`, rule: "Positive 14-period ATR; breakout no more than 1.5× ATR beyond the trigger." },
  ];
  const review = data.latest_review;
  return <section id="strategy-lab" className="station-strategies" aria-label="Strategies and learning">
    <div className="station-pane-title"><h3><FlaskConical size={16} /> Strategies &amp; learning</h3><span>Next review {when(data.next_review)}</span></div>
    <p className="strategy-intro">Testing breakout timing: do earlier entries or stronger confirmation improve results after costs?</p>
    <div className="strategy-cards">{data.variants.map(variant => <button type="button" key={variant.version} className={selected.version === variant.version ? "selected" : ""} aria-pressed={selected.version === variant.version} onClick={() => setInspected(variant.version)}>
      <div><strong>{names[variant.version] ?? variant.version}</strong><span>{variant.version === data.active_version ? "Primary rule" : "Comparison"}</span></div>
      <p>{variant.rules.lookback}-minute high · &gt;{variant.rules.volume_multiple}× volume</p>
      <div className="strategy-score"><strong className={Number(variant.account.net_pnl) >= 0 ? "station-positive" : "station-negative"}>{money(variant.account.net_pnl)}</strong><span>net · {variant.account.closed} closed trades</span></div>
      {!variant.account.valuation_fresh && <small>Last recorded valuation</small>}
    </button>)}</div>
    <p className="station-small">Separate BTC/ETH paper comparisons; net values include costs. These accounts share market history and do not establish independent success.</p>
    <div className="strategy-focus"><div><p className="station-kicker">CURRENT RESEARCH QUESTION</p><h4>{questions[selected.version] ?? "Review this version's recorded evidence."}</h4></div><span>{names[selected.version]} · {symbol.replace(/USD$/, " / USD")}</span></div>
    {!current && <p className="station-inline-note">Signal evidence is {unavailable ? "unavailable" : "warming up or stale"}. No current signal is inferred.</p>}
    <div className="strategy-signals">{signals.map(signal => {
      const passed = current ? selected.checks[signal.key] : null;
      return <article key={signal.key}><div><span>{signal.name}</span><span className={passed ? "station-positive" : "station-muted"}>{passed ? <Check size={13} /> : <Circle size={11} />}{passed === null ? "Unknown" : passed ? "Met" : "Waiting"}</span></div><strong>{signal.value}</strong><p>{signal.rule}</p></article>;
    })}</div>
    <p className="station-small">{selected.feature_closed_at ? `Recorded at ${when(selected.feature_closed_at)}. ` : ""}Signals use completed candles. New entries also need a fresh quote, spread at most 0.25%, sufficient visible liquidity and available cash/risk capacity.</p>
    <div className="strategy-exits" aria-label="Stop loss and exit rules">
      <article><span>01 / INITIAL PROTECTION</span><h4>{selected.rules.stop_atr}× ATR below entry</h4><p>The stop distance follows recent volatility. It is not a fixed percentage.</p></article>
      <article><span>02 / FOLLOW THE MOVE</span><h4>Trail after a 1R price gain</h4><p>After the bid rises by the initial stop distance, the stop follows 1× current ATR below the bid. It only moves upward.</p></article>
      <article><span>03 / TIME EXITS</span><h4>10-minute progress check</h4><p>Exit if the bid has never reached 1R after 10 minutes. Exit any remaining position after 45 minutes; there is no fixed profit target.</p></article>
    </div>
    <p className="station-small">1R means the initial price-to-stop distance. Trail activation can still leave a loss after fees. A stop triggers a simulated exit request; its eventual fill can be worse after a gap.</p>
    <details className="strategy-risk"><summary>Position sizing &amp; execution assumptions</summary><p>At most 50% of equity in one position and 90% total exposure. Planned risk is capped at 2.5% per entry and 5% combined, including modeled costs. Paper fills use a later fresh book, up to 10% of displayed liquidity, a 0.10% fee each side and 0.02% adverse price each side. Stops do not guarantee the planned loss limit.</p></details>
    <div className="strategy-review"><div><p className="station-kicker">WHAT THE REVIEW IS LEARNING</p><h4>{review ? `Latest review selected ${names[review.selected] ?? review.selected}` : "Collecting forward outcomes for the first review"}</h4><p>{review?.reason ?? "A review needs new observed trades before it can compare the frozen rules."}</p>{review && <span>Reviewed at {when(review.at)} · {data.review_count} reviews recorded</span>}</div><div><strong>Evidence needed before a change</strong><p>Two separate four-hour windows, with at least 10 completed trades each for the current rule and challenger. Higher returns must survive extra fees without worse drawdown.</p>{review && <p>For {names[selected.version]} at the last review: {review.windows.map((w, i) => <span key={w.end}>{i > 0 ? " · " : ""}{w.trades[selected.version] ?? 0}/10 trades in window {i + 1}</span>)}.</p>}</div></div>
    <p className="strategy-boundary">Learning now: comparing frozen rules against new outcomes. Trainable models and LLM research roles are still being qualified.</p>
  </section>;
});
