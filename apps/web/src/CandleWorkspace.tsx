import { useEffect, useRef, useState } from "react";
import { CandlestickSeries, ColorType, CrosshairMode, HistogramSeries, LineSeries,
  createChart, createSeriesMarkers, type IChartApi, type ISeriesApi, type UTCTimestamp } from "lightweight-charts";
import type { Candle } from "./MarketChart";
import { useEvidenceRead } from "./useEvidenceRead";
import "./candle-workspace.css";

const frames = { "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400 };
const windows = { recent: "Recent 240 candles", week: "1 week", month: "1 month",
  six_months: "6 months", year: "1 year" };
type Frame = keyof typeof frames;
type Window = keyof typeof windows;
type Command = { symbol: string; timeframe: Frame; window: Window; request_id: string };
type Indicator = "sma10" | "sma50" | "sma100" | "vwap";
type Point = { open_ms: number; sma10: string | null; sma50: string | null;
  sma100: string | null; vwap: string | null; volume_ratio: string | null };
type Zone = { id: string; kind: string; price: string; low: string; high: string;
  touches: number; confirmed_at_ms: number; last_touch_ms: number };
type Pattern = { id: string; kind: string; bar_open_ms: number; level_id: string;
  level_price: string; volume_ratio: string | null; volume_confirmed: boolean | null; reason: string };
type Analysis = { version: string; symbol: string; timeframe: Frame; window: Window;
  seconds: number; source: string; observed_at: number;
  coverage: { requested_start_ms: number; requested_end_ms: number; actual_start_ms: number;
    actual_end_ms: number; bar_count: number; expected_bars: number; missing_bars: number; truncated: boolean;
    patterns_observed: number; patterns_omitted_from_display: number; latest_segment_candles: number };
  candles: Candle[]; indicators: { points: Point[] }; zones: Zone[]; patterns: Pattern[];
  parameters: Record<string, unknown>; limitations: string[] };
type Run = { id: number; tool: string; symbol: string; status: string; request_id: string;
  query: string | Record<string, unknown>; started: number; error: string | null;
  result: Record<string, unknown> | null; candle_analysis?: Analysis };
type RunSummary = { id: number; tool: string; symbol: string; status: string; started: number };
type Saved = { command: Command | null; error: string | null };
const pendingKey = "qtrades-candle-pattern-pending-v1";
const receiptKey = "qtrades-candle-pattern-receipt-v1";
const colors: Record<Indicator, string> = { sma10: "#63b3ff", sma50: "#f8c66a", sma100: "#e2a2ff", vwap: "#7be0bf" };
const labels: Record<Indicator, string> = { sma10: "SMA 10", sma50: "SMA 50", sma100: "SMA 100", vwap: "VWAP · 50 candles" };
const stamp = (ms: number) => new Date(ms).toLocaleString([], { timeZone: "America/Denver",
  month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
const decimal = (value: string | null | undefined) => value == null ? "Unavailable" :
  Number(value).toLocaleString("en-US", { maximumFractionDigits: 8 });
const title = (value: string) => value.replaceAll("_", " ");
const finiteDecimal = (value: unknown) => typeof value === "string" && value.length <= 100 &&
  /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i.test(value) && Number.isFinite(Number(value));
const nullableDecimal = (value: unknown) => value === null || finiteDecimal(value);
const count = (value: unknown) => Number.isSafeInteger(value) && Number(value) >= 0;

function savedCommand(): Saved {
  try {
    const raw = localStorage.getItem(pendingKey);
    if (!raw) return { command: null, error: null };
    const command = JSON.parse(raw) as Command;
    if (!command || !/^[A-Z0-9]{3,24}$/.test(command.symbol) || !Object.hasOwn(frames, command.timeframe) ||
        !Object.hasOwn(windows, command.window) || !/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(command.request_id)) throw new Error();
    return { command, error: null };
  } catch {
    return { command: null, error: "Saved request recovery is unreadable. No new study can be sent until its outcome is reconciled." };
  }
}

async function pendingLock(work: () => void) {
  if (!navigator.locks) throw new Error("This window cannot safely save requests for recovery.");
  await navigator.locks.request(pendingKey, { ifAvailable: true }, lock => {
    if (!lock) throw new Error("Another window is saving a study request. Its recovery record is retained.");
    work();
  });
}

function selectedReceipt(): number | null {
  const params = new URLSearchParams(location.hash.split("?")[1] ?? "");
  const explicit = params.get("candle_run");
  if (explicit != null) return /^\d+$/.test(explicit) && Number.isSafeInteger(Number(explicit)) ? Number(explicit) : null;
  try {
    const saved = JSON.parse(localStorage.getItem(receiptKey) ?? "null") as { id: number; symbol: string } | null;
    if (!saved || !Number.isSafeInteger(saved.id) || saved.id <= 0 || !/^[A-Z0-9]{3,24}$/.test(saved.symbol) ||
        params.has("symbol") && params.get("symbol") !== saved.symbol) return null;
    return saved.id;
  } catch { return null; }
}

function validateRun(value: Run, expected: { id?: number; command?: Command }): void {
  if (!value || !Number.isSafeInteger(value.id) || value.id <= 0 || value.tool !== "candle_patterns" ||
      typeof value.symbol !== "string" || !/^[A-Z0-9]{3,24}$/.test(value.symbol) ||
      typeof value.status !== "string" || !["running", "finalizing", "completed", "failed", "interrupted"].includes(value.status) ||
      expected.id != null && value.id !== expected.id) throw new Error("Saved candle study identity differs; no substitute was loaded.");
  const query = typeof value.query === "string" ? JSON.parse(value.query) as Record<string, unknown> : value.query;
  if (expected.command && (value.request_id !== expected.command.request_id || value.symbol !== expected.command.symbol ||
      query?.symbol !== expected.command.symbol || query?.timeframe !== expected.command.timeframe ||
      query?.window !== expected.command.window)) throw new Error("Saved study does not match the original request.");
  if (value.status !== "completed") return;
  const analysis = value.candle_analysis;
  if (!analysis || analysis.version !== "candle-patterns-v1" || analysis.symbol !== value.symbol ||
      !Object.hasOwn(frames, analysis.timeframe) || !Object.hasOwn(windows, analysis.window) || analysis.seconds !== frames[analysis.timeframe] ||
      typeof analysis.source !== "string" || !Number.isFinite(analysis.observed_at) ||
      query?.symbol !== analysis.symbol || query?.timeframe !== analysis.timeframe || query?.window !== analysis.window ||
      !Array.isArray(analysis.candles) || analysis.candles.length > 5000 ||
      !Array.isArray(analysis.indicators?.points) || analysis.indicators.points.length !== analysis.candles.length ||
      !Array.isArray(analysis.zones) || !Array.isArray(analysis.patterns) ||
      !Array.isArray(analysis.limitations) || !analysis.limitations.every(v => typeof v === "string")) {
    throw new Error("The saved analysis is incomplete or its scope differs. The receipt remains retained.");
  }
  if (!analysis.parameters || JSON.stringify(analysis.parameters.sma_periods) !== "[10,50,100]" ||
      analysis.parameters.vwap_window_candles !== 50 || analysis.parameters.volume_baseline_candles !== 20 ||
      analysis.parameters.volume_confirmation_multiple !== "1.5") throw new Error("This study uses different indicator settings. Its original receipt remains retained.");
  const coverage = analysis.coverage;
  if (!coverage || coverage.bar_count !== analysis.candles.length ||
      ![coverage.bar_count, coverage.expected_bars, coverage.missing_bars, coverage.patterns_observed,
        coverage.patterns_omitted_from_display, coverage.latest_segment_candles].every(count) ||
      typeof coverage.truncated !== "boolean" ||
      ![coverage.requested_start_ms, coverage.requested_end_ms, coverage.actual_start_ms, coverage.actual_end_ms].every(Number.isFinite)) {
    throw new Error("Saved history coverage is unavailable; the chart was not substituted.");
  }
  const times = new Set<number>();
  const step = analysis.seconds * 1000;
  analysis.candles.forEach((bar, i) => {
    if (!Number.isSafeInteger(bar.open_ms) || bar.open_ms % step !== 0 || bar.close_ms !== bar.open_ms + step - 1 ||
        ![bar.open, bar.high, bar.low, bar.close, bar.volume].every(finiteDecimal) || Number(bar.volume) < 0 ||
        Number(bar.low) <= 0 || Number(bar.low) > Math.min(Number(bar.open), Number(bar.close)) ||
        Number(bar.high) < Math.max(Number(bar.open), Number(bar.close)) ||
        i > 0 && bar.open_ms <= analysis.candles[i - 1].open_ms) throw new Error("Saved candle values failed validation.");
    times.add(bar.open_ms);
    const point = analysis.indicators.points[i];
    if (point.open_ms !== bar.open_ms || ![point.sma10, point.sma50, point.sma100, point.vwap, point.volume_ratio].every(nullableDecimal)) {
      throw new Error("Saved indicator values failed validation.");
    }
  });
  if (analysis.candles.length && (coverage.actual_start_ms !== analysis.candles[0].open_ms ||
      coverage.actual_end_ms !== analysis.candles.at(-1)!.close_ms ||
      coverage.actual_end_ms - coverage.actual_start_ms >= 5000 * step)) throw new Error("Coverage differs from the bounded returned candles.");
  if (analysis.patterns.some(p => typeof p.id !== "string" || typeof p.kind !== "string" ||
      !times.has(p.bar_open_ms) || !finiteDecimal(p.level_price) || !nullableDecimal(p.volume_ratio) ||
      ![true, false, null].includes(p.volume_confirmed) || typeof p.reason !== "string") ||
      analysis.zones.some(z => typeof z.id !== "string" || typeof z.kind !== "string" ||
      ![z.price, z.low, z.high].every(finiteDecimal) || !count(z.touches) ||
      !Number.isFinite(z.confirmed_at_ms) || !Number.isFinite(z.last_touch_ms))) throw new Error("Saved pattern or level data failed validation.");
}

function CandleStudyChart({ analysis, selected, onSelect }: {
  analysis: Analysis; selected: number | null; onSelect: (time: number) => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const [enabled, setEnabled] = useState<Indicator[]>(["sma10", "sma50", "sma100", "vwap"]);
  const [levels, setLevels] = useState(true);
  const [chartError, setChartError] = useState<string | null>(null);
  const visibleLines = useRef(enabled);
  const choose = useRef(onSelect);
  choose.current = onSelect;
  visibleLines.current = enabled;
  const lines = useRef<Partial<Record<Indicator, ISeriesApi<"Line">[]>>>({});
  const timeline = useRef<number[]>([]);
  useEffect(() => {
    if (!host.current) return;
    let instance: IChartApi | null = null;
    try {
      instance = createChart(host.current, {
        autoSize: true, height: 390,
        layout: { background: { type: ColorType.Solid, color: "#0e2026" }, textColor: "#bcd1cd" },
        grid: { vertLines: { color: "#243e43" }, horzLines: { color: "#243e43" } },
        crosshair: { mode: CrosshairMode.Normal },
        timeScale: { timeVisible: true, secondsVisible: false },
        localization: { timeFormatter: (time: unknown) => stamp(Number(time) * 1000) },
      });
      chart.current = instance;
      const candles = instance.addSeries(CandlestickSeries, {
        upColor: "#78d7b2", downColor: "#f09c91", wickUpColor: "#78d7b2", wickDownColor: "#f09c91", borderVisible: false,
      });
      candles.priceScale().applyOptions({ scaleMargins: { top: .08, bottom: .26 } });
      const data = analysis.candles.map(b => ({ time: (b.open_ms / 1000) as UTCTimestamp,
        open: Number(b.open), high: Number(b.high), low: Number(b.low), close: Number(b.close) }));
      const span = data.length ? Math.max(.00000001, Math.max(...data.map(b => b.high)) - Math.min(...data.map(b => b.low))) : 1;
      const precision = Math.min(8, Math.max(2, Math.ceil(-Math.log10(span / 100))));
      candles.applyOptions({ priceFormat: { type: "price", precision, minMove: 10 ** -precision } });
      const gaps = data.flatMap((bar, i) => i > 0 ? Array.from({ length: Math.max(0,
        (bar.time - data[i - 1].time) / analysis.seconds - 1) }, (_, gap) =>
        ({ time: (data[i - 1].time + (gap + 1) * analysis.seconds) as UTCTimestamp })) : []);
      const allTimes = [...data, ...gaps].sort((a, b) => a.time - b.time);
      timeline.current = allTimes.map(bar => bar.time * 1000);
      candles.setData(allTimes);
      const volume = instance.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "volume", lastValueVisible: false, priceLineVisible: false });
      volume.priceScale().applyOptions({ scaleMargins: { top: .82, bottom: 0 }, visible: false });
      volume.setData(analysis.candles.map(b => ({ time: (b.open_ms / 1000) as UTCTimestamp,
        value: Number(b.volume), color: Number(b.close) >= Number(b.open) ? "#78d7b270" : "#f09c9170" })));
      const segmentBounds: Partial<Record<Indicator, { from: number; to: number; points: number }[]>> = {};
      for (const key of Object.keys(colors) as Indicator[]) {
        const segments: { time: UTCTimestamp; value: number }[][] = [];
        let segment: { time: UTCTimestamp; value: number }[] | null = null;
        for (const point of analysis.indicators.points) {
          if (point[key] == null) { segment = null; continue; }
          const time = (point.open_ms / 1000) as UTCTimestamp;
          if (!segment || time !== segment.at(-1)!.time + analysis.seconds) {
            segment = []; segments.push(segment);
          }
          segment.push({ time, value: Number(point[key]) });
        }
        // Lightweight Charts removes whitespace from line plots. Separate series
        // keep missing intervals and post-gap warmup disconnected instead.
        lines.current[key] = segments.map(points => {
          const line = instance!.addSeries(LineSeries, { color: colors[key], lineWidth: 2, priceLineVisible: false,
            lastValueVisible: false, crosshairMarkerVisible: false, visible: visibleLines.current.includes(key) });
          line.setData(points); return line;
        });
        segmentBounds[key] = segments.map(points => ({ from: points[0].time * 1000,
          to: points.at(-1)!.time * 1000, points: points.length }));
      }
      host.current.dataset.indicatorSegments = JSON.stringify(segmentBounds);
      if (levels) for (const zone of analysis.zones.slice(-30)) candles.createPriceLine({
        price: Number(zone.price), color: zone.kind.includes("support") ? "#7ed4b380" : "#eda89c80", lineWidth: 1,
        lineStyle: 2, axisLabelVisible: false, title: title(zone.kind),
      });
      const patternsByCandle = new Map(analysis.patterns.slice(-100).map(pattern => [pattern.bar_open_ms, pattern]));
      const markers = [...patternsByCandle.values()].map(pattern => ({
        time: (pattern.bar_open_ms / 1000) as UTCTimestamp,
        position: "aboveBar" as const, shape: "circle" as const,
        color: pattern.volume_confirmed === true ? "#f8c66a" : "#b3bfc7",
        text: "",
      })).sort((a, b) => a.time - b.time);
      createSeriesMarkers(candles, markers);
      instance.subscribeClick(event => { if (typeof event.time === "number") choose.current(Number(event.time) * 1000); });
      instance.subscribeCrosshairMove(event => { if (typeof event.time === "number") choose.current(Number(event.time) * 1000); });
      instance.timeScale().subscribeVisibleTimeRangeChange(range => {
        if (host.current) {
          host.current.dataset.visibleStartMs = range ? String(Number(range.from) * 1000) : "";
          host.current.dataset.visibleEndMs = range ? String(Number(range.to) * 1000) : "";
        }
      });
      instance.timeScale().setVisibleLogicalRange({ from: Math.max(0, allTimes.length - 100), to: allTimes.length + 2 });
      setChartError(null);
    } catch {
      setChartError("The saved chart could not be drawn. Its candle and pattern evidence remains available below.");
    }
    return () => { instance?.remove(); chart.current = null; lines.current = {}; timeline.current = []; };
  }, [analysis, levels]);
  useEffect(() => {
    for (const key of Object.keys(colors) as Indicator[]) for (const line of lines.current[key] ?? []) line.applyOptions({ visible: enabled.includes(key) });
  }, [enabled]);
  useEffect(() => {
    if (!chart.current) return;
    if (selected == null) {
      chart.current.timeScale().setVisibleLogicalRange({ from: Math.max(0, timeline.current.length - 100), to: timeline.current.length + 2 });
      return;
    }
    const index = timeline.current.indexOf(selected);
    const range = chart.current.timeScale().getVisibleLogicalRange();
    if (index >= 0 && range && (index < range.from || index > range.to)) {
      chart.current.timeScale().setVisibleLogicalRange({ from: Math.max(0, index - 25), to: index + 25 });
    }
  }, [selected, analysis]);
  return <div className="candle-study-chart">
    <div className="candle-chart-controls" role="group" aria-label="Candle chart overlays">
      {(Object.keys(colors) as Indicator[]).map(key => <button key={key} type="button" aria-pressed={enabled.includes(key)}
        style={{ borderColor: colors[key] }} onClick={() => setEnabled(old => old.includes(key) ? old.filter(k => k !== key) : [...old, key])}>{labels[key]}</button>)}
      <button type="button" aria-pressed={levels} onClick={() => setLevels(!levels)}>Level zones</button>
      <button type="button" onClick={() => chart.current?.timeScale().fitContent()}>Fit saved history</button>
    </div>
    {chartError && <p role="alert">{chartError}</p>}
    <div ref={host} role="img" aria-label={`${analysis.symbol} closed ${analysis.timeframe} candles with volume, SMA 10, 50, 100 and 50-candle VWAP`} />
    <p className="candle-help">Drag to pan; scroll or pinch to zoom. Dots mark candles with recorded patterns; choose a named pattern below for its reason and volume. Chart axis UTC; inspection and crosshair Mountain time. Candles close on UTC interval boundaries. Missing candle intervals stay empty; indicator lines restart only after their contiguous warmup. Zone lines summarize the saved study; their confirmation times below show when they first became known.</p>
    <p className="chart-attribution"><a href="https://www.tradingview.com/" target="_blank" rel="noreferrer">TradingView Lightweight Charts™</a> · Copyright © 2025 TradingView, Inc.</p>
  </div>;
}

function StudyResult({ run }: { run: Run }) {
  const analysis = run.candle_analysis!;
  const [selected, setSelected] = useState<number | null>(null);
  const [pattern, setPattern] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const bar = selected === null ? analysis.candles.at(-1) : analysis.candles.find(b => b.open_ms === selected);
  const point = analysis.indicators.points.find(p => p.open_ms === bar?.open_ms);
  const chosen = analysis.patterns.find(p => p.id === pattern);
  const zone = analysis.zones.find(z => z.id === chosen?.level_id);
  const coverage = analysis.coverage;
  const patterns = [...analysis.patterns].reverse();
  return <div className="candle-study-result">
    <div className="candle-study-heading"><h4>{analysis.symbol.replace(/USD$/, " / USD")} · {analysis.timeframe} candles</h4>
      <span>Saved study #{run.id} · {stamp(analysis.observed_at * 1000)} MT</span></div>
    <p className="candle-coverage"><strong>{coverage.bar_count.toLocaleString()} actual closed candles</strong> of {coverage.expected_bars.toLocaleString()} requested · {coverage.missing_bars.toLocaleString()} missing within the bounded retrieval.
      {coverage.truncated && <strong> Requested history was truncated to the bounded retrieval.</strong>}<br />
      Requested {stamp(coverage.requested_start_ms)} to {stamp(coverage.requested_end_ms)} MT. Returned {stamp(coverage.actual_start_ms)} to {stamp(coverage.actual_end_ms)} MT.<br />
      Latest contiguous segment: {coverage.latest_segment_candles.toLocaleString()} candles. {coverage.patterns_omitted_from_display > 0 && `${coverage.patterns_omitted_from_display.toLocaleString()} older pattern records are outside the retained display bound.`}</p>
    <CandleStudyChart analysis={analysis} selected={selected} onSelect={setSelected} />
    <section className="candle-inspector" aria-label="Selected candle and volume">
      <h4>{bar ? `${stamp(bar.open_ms)} MT · closed ${analysis.timeframe} candle` :
        `${selected == null ? "Selected interval" : stamp(selected) + " MT"} · no recorded candle available`}</h4>
      <div className="candle-actions" role="group" aria-label="Inspect candle interval">
        <button type="button" disabled={!analysis.candles.length} onClick={() => { setPattern(null); setSelected(analysis.candles[0].open_ms); }}>First interval</button>
        <button type="button" disabled={!analysis.candles.length || (selected ?? bar!.open_ms) <= coverage.actual_start_ms}
          onClick={() => { setPattern(null); setSelected((selected ?? bar!.open_ms) - analysis.seconds * 1000); }}>Previous interval</button>
        <button type="button" disabled={!analysis.candles.length || (selected ?? bar!.open_ms) >= analysis.candles.at(-1)!.open_ms}
          onClick={() => { setPattern(null); setSelected((selected ?? bar!.open_ms) + analysis.seconds * 1000); }}>Next interval</button>
        <button type="button" disabled={!analysis.candles.length} onClick={() => { setPattern(null); setSelected(null); }}>Latest interval</button>
      </div>
      {bar && <div className="candle-metrics"><span>Open <strong>{decimal(bar.open)}</strong></span><span>High <strong>{decimal(bar.high)}</strong></span>
        <span>Low <strong>{decimal(bar.low)}</strong></span><span>Close <strong>{decimal(bar.close)}</strong></span><span>Volume <strong>{decimal(bar.volume)}</strong></span>
        <span>Volume / prior median <strong>{point?.volume_ratio == null ? "Unavailable" : `${decimal(point.volume_ratio)}×`}</strong></span></div>}
      <div className="candle-metrics">{(Object.keys(colors) as Indicator[]).map(key => <span key={key} style={{ color: colors[key] }}>{labels[key]} <strong>{decimal(point?.[key])}</strong></span>)}</div>
      <p>Each SMA averages 10, 50 or 100 consecutive closed candles of this chart interval. Unavailable values indicate insufficient contiguous history. VWAP approximates typical price (HLC3) weighted by volume over 50 candles; it is not a trade-level or full-session VWAP. Volume compares this candle with the median of the preceding 20 candles, excluding itself; the baseline is unavailable if any volume is zero. 1.5× is descriptive confirmation.</p>
    </section>
    <div className="candle-pattern-grid">
      <section aria-label="Recorded candle patterns"><h4>Patterns to inspect · {patterns.length.toLocaleString()}</h4>
        <p>Observed price behavior around confirmed levels. These labels do not establish an after-cost trading edge.</p>
        <div className="candle-pattern-list">{patterns.slice(page * 20, page * 20 + 20).map(item => <button key={item.id} type="button" aria-pressed={pattern === item.id}
          onClick={() => { setPattern(item.id); setSelected(item.bar_open_ms); }}><strong>{title(item.kind)}</strong><time>{stamp(item.bar_open_ms)} MT</time>
          <span>Level {decimal(item.level_price)} · volume {item.volume_ratio == null ? "unknown" : `${decimal(item.volume_ratio)}×`}</span></button>)}</div>
        {!patterns.length && <p>No pattern was classified in the returned history.</p>}
        {patterns.length > 20 && <div className="candle-actions"><button type="button" disabled={page === 0} onClick={() => setPage(page - 1)}>Newer patterns</button>
          <span>Page {page + 1} of {Math.ceil(patterns.length / 20)}</span><button type="button" disabled={(page + 1) * 20 >= patterns.length} onClick={() => setPage(page + 1)}>Older patterns</button></div>}
      </section>
      <section className="candle-pattern-detail" aria-label="Pattern details"><h4>{chosen ? title(chosen.kind) : "Select a pattern"}</h4>
        {chosen ? <><p>{chosen.reason}</p><p>{stamp(chosen.bar_open_ms)} MT · level {decimal(chosen.level_price)}.<br />
          Volume {chosen.volume_ratio == null ? "baseline unavailable" : `${decimal(chosen.volume_ratio)}× prior median`} · {chosen.volume_confirmed == null ? "confirmation unavailable" : chosen.volume_confirmed ? "volume confirmation present" : "volume confirmation absent"}.</p>
          {zone ? <p>{title(zone.kind)} zone {decimal(zone.low)} – {decimal(zone.high)} · {zone.touches} touches.<br />
            Confirmed {stamp(zone.confirmed_at_ms)} MT; last touch {stamp(zone.last_touch_ms)} MT. Touch totals summarize the saved study, including later candles.</p> : <p>This older level is outside the retained zone display. Its original pattern price and reason remain above.</p>}</> : <p>Choose a row to move to its candle and inspect the recorded reason, level and volume baseline.</p>}
      </section>
    </div>
    <details><summary>Coverage, settings and limitations</summary><p>Source: {analysis.source}. Historical public candles were retrieved for this request; they were not observed inputs to earlier paper decisions.</p>
      <ul>{analysis.limitations.map((limitation, i) => <li key={i}>{limitation}</li>)}</ul><pre>{JSON.stringify(analysis.parameters, null, 2)}</pre></details>
  </div>;
}

export function CandleWorkspace({ symbol, savedRuns, onChooseMarket }: {
  symbol: string; savedRuns: RunSummary[]; onChooseMarket: (symbol: string, runId: number) => void;
}) {
  const [frame, setFrame] = useState<Frame>("5m");
  const [window, setWindow] = useState<Window>("recent");
  const [initial] = useState(savedCommand);
  const [pending, setPending] = useState<Command | null>(initial.command);
  const [storageError, setStorageError] = useState<string | null>(initial.error);
  const [run, setRun] = useState<Run | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const { begin, cancel } = useEvidenceRead();
  const selection = useRef({ symbol, frame, window });
  selection.current = { symbol, frame, window };
  const chooseMarket = useRef(onChooseMarket);
  chooseMarket.current = onChooseMarket;
  const requestInFlight = useRef(false);
  const restored = useRef<number | null>(null);
  const mounted = useRef(true);
  const scope = `${symbol}:${frame}:${window}`;
  const currentScope = useRef(scope);
  currentScope.current = scope;

  useEffect(() => {
    cancel();
    if (run?.symbol !== symbol || run.candle_analysis?.timeframe !== frame || run.candle_analysis.window !== window) {
      setRun(null); restored.current = null;
    }
    setBusy(false); setError(null);
  }, [scope, cancel]);
  useEffect(() => {
    mounted.current = true;
    const listen = (event: StorageEvent) => {
      if (event.key !== pendingKey) return;
      const saved = savedCommand(); setPending(saved.command); setStorageError(saved.error);
      if (saved.command) setNotice("Another window has a saved study request. Reopen its exact result before a new study.");
    };
    addEventListener("storage", listen);
    return () => { mounted.current = false; removeEventListener("storage", listen); };
  }, []);

  async function accept(value: Run, command?: Command, navigate = true, isCurrent: () => boolean = () => true) {
    validateRun(value, { command });
    if (["completed", "failed", "interrupted"].includes(value.status)) {
      const unresolved = savedCommand().command;
      if (unresolved?.request_id === value.request_id) {
        await pendingLock(() => {
          if (localStorage.getItem(pendingKey) !== JSON.stringify(unresolved)) throw new Error("Recovery state changed in another window; its request remains saved.");
          localStorage.removeItem(pendingKey);
        });
        if (mounted.current) setPending(null);
      }
    }
    if (!mounted.current || !isCurrent()) return;
    localStorage.setItem(receiptKey, JSON.stringify({ id: value.id, symbol: value.symbol }));
    restored.current = value.id;
    if (navigate) {
      const params = new URLSearchParams(location.hash.split("?")[1] ?? "");
      params.set("candle_run", String(value.id));
      history.replaceState(null, "", `#markets?${params}`);
    }
    setRun(value);
    if (value.candle_analysis) {
      setFrame(value.candle_analysis.timeframe); setWindow(value.candle_analysis.window);
      if (value.symbol !== selection.current.symbol) chooseMarket.current(value.symbol, value.id);
    }
    setError(null); setNotice(value.status === "completed" ? "The original saved study is open." :
      value.status === "running" || value.status === "finalizing" ? "This study is still running. Reopen its saved result; no repeat request was sent." : "The original unsuccessful outcome is retained.");
  }

  async function open(id: number, navigate = true) {
    const request = begin(30000);
    setBusy(true); setError(null); setRun(null); restored.current = id;
    try {
      const response = await fetch(`/api/research/tools/runs/${id}`, { cache: "no-store", signal: request.signal });
      if (!response.ok) throw new Error("The saved candle study is unavailable. No new study was requested.");
      const value = await response.json() as Run;
      validateRun(value, { id });
      if (request.isCurrent()) await accept(value, undefined, navigate, request.isCurrent);
    } catch (cause) {
      if (request.isCurrent()) setError(cause instanceof Error ? cause.message : "Saved study unavailable.");
    } finally { if (request.isCurrent()) setBusy(false); }
  }

  useEffect(() => {
    const restore = () => { const id = selectedReceipt(); if (id != null && id !== restored.current) void open(id, false); };
    restore(); addEventListener("hashchange", restore); addEventListener("popstate", restore);
    return () => { removeEventListener("hashchange", restore); removeEventListener("popstate", restore); };
  }, []);

  async function load() {
    if (busy || pending || storageError || requestInFlight.current) return;
    const command: Command = { symbol, timeframe: frame, window, request_id: crypto.randomUUID() };
    const expectedScope = scope;
    requestInFlight.current = true; setBusy(true); setError(null); setRun(null); setNotice(null);
    const request = begin(30000);
    const dispatched: { response: Promise<Response> | null } = { response: null };
    try {
      await pendingLock(() => {
        if (!mounted.current || !request.isCurrent() || request.signal.aborted || expectedScope !== currentScope.current) throw new Error("The selected scope changed before the request was saved. No study was sent.");
        if (localStorage.getItem(pendingKey) !== null) throw new Error("A saved request already exists. Reopen its result before requesting another study.");
        localStorage.setItem(pendingKey, JSON.stringify(command));
        // No asynchronous gap between durable recovery and starting the request.
        // A later abort cannot establish that the saved study did not commit.
        dispatched.response = fetch("/api/research/candle-patterns", { method: "POST",
          headers: { "Content-Type": "application/json", "X-Local-Operator": "1" },
          body: JSON.stringify(command), signal: request.signal });
      });
      if (mounted.current) setPending(command);
      if (!dispatched.response) throw new Error("No study request was dispatched.");
      const response = await dispatched.response;
      const value = await response.json() as Run & { detail?: string };
      if ([403, 422, 429].includes(response.status)) {
        // These route/schema refusals precede journal.start; they are known rejections,
        // unlike timeouts and 503 responses that may follow a committed receipt.
        const reason = typeof value.detail === "string" ? value.detail : "The study request was refused before it started.";
        await pendingLock(() => {
          if (localStorage.getItem(pendingKey) !== JSON.stringify(command)) throw new Error("Saved recovery state changed; the other request remains retained.");
          localStorage.setItem("qtrades-candle-pattern-refusal-v1", JSON.stringify({ command, status: response.status, reason, at: Date.now() }));
          localStorage.removeItem(pendingKey);
        });
        if (mounted.current) setPending(null);
        if (request.isCurrent() && expectedScope === currentScope.current) {
          setError(reason); setNotice(`The original request was refused (${response.status}); no study started. Its refusal is retained.`);
        }
        return;
      }
      if (!response.ok) throw new Error(typeof value.detail === "string" ? value.detail : "The candle study was not confirmed.");
      validateRun(value, { command });
      if (request.isCurrent() && expectedScope === currentScope.current) await accept(value, command, true,
        () => request.isCurrent() && expectedScope === currentScope.current);
    } catch (cause) {
      const saved = savedCommand();
      const recovery = saved.command?.request_id === command.request_id
        ? "The original request is saved; find its result before starting another."
        : dispatched.response ? "The dispatched outcome is unconfirmed; saved recovery could not be verified."
        : saved.command ? "No new study was sent. Another window's saved request is retained."
        : "No study was sent.";
      if (mounted.current && expectedScope === currentScope.current) setError(`${cause instanceof Error ? cause.message : "The study response was not confirmed."} ${recovery}`);
      if (mounted.current) { setPending(saved.command); setStorageError(saved.error); }
    } finally {
      requestInFlight.current = false;
      if (mounted.current && expectedScope === currentScope.current) setBusy(false);
    }
  }

  async function recover() {
    if (!pending || busy) return;
    const command = pending;
    const request = begin(30000); setBusy(true); setError(null); setRun(null);
    try {
      const response = await fetch(`/api/research/candle-patterns/requests/${encodeURIComponent(command.request_id)}`, { cache: "no-store", signal: request.signal });
      if (response.status === 404) throw new Error("No saved receipt is available yet. The earlier request may still finish; its outcome remains unknown.");
      if (!response.ok) throw new Error("The earlier request cannot be reconciled right now. Its recovery record remains saved.");
      const value = await response.json() as Run;
      if (request.isCurrent()) await accept(value, command, true, request.isCurrent);
    } catch (cause) { if (request.isCurrent()) setError(cause instanceof Error ? cause.message : "Request outcome remains unknown."); }
    finally { if (request.isCurrent()) setBusy(false); }
  }

  const shown = run?.symbol === symbol && run.candle_analysis?.timeframe === frame && run.candle_analysis.window === window ? run : null;
  return <section className="candle-workspace" aria-labelledby="candle-workspace-title">
    <header><div><p className="station-kicker">CLOSED CANDLES · DESCRIPTIVE RESEARCH</p><h3 id="candle-workspace-title">Candle &amp; volume workspace</h3></div><span>{symbol.replace(/USD$/, " / USD")}</span></header>
    <p className="candle-intro">Inspect support and resistance behavior across chart intervals, with simple moving averages and volume. Load a bounded historical study when you need it; saved studies keep their original observations.</p>
    <div className="candle-load-controls">
      <div role="group" aria-label="Candle interval" className="candle-frame-buttons">{(Object.keys(frames) as Frame[]).map(item => <button type="button" key={item} aria-pressed={frame === item} onClick={() => setFrame(item)}>{item}</button>)}</div>
      <label>History <select aria-label="Candle history window" value={window} onChange={event => setWindow(event.target.value as Window)}>{(Object.keys(windows) as Window[]).map(item => <option key={item} value={item}>{windows[item]}</option>)}</select></label>
      <button className="candle-load-button" type="button" disabled={busy || !!pending || !!storageError || !navigator.locks || !/^[A-Z0-9]{3,24}$/.test(symbol)} onClick={() => void load()}>{busy ? "Reading saved evidence…" : `Load ${frame} study`}</button>
    </div>
    <p className="candle-help">SMA periods are candle counts of the selected interval. Up to 5,000 actual candles per study; requested longer windows may be truncated. This inspector does not change account strategies or place orders.</p>
    {pending && <div className="candle-pending" role="status"><p>Awaiting the original {pending.symbol} · {pending.timeframe} · {windows[pending.window]} request. Leaving this view does not undo a saved study.</p>
      <button type="button" disabled={busy} onClick={() => void recover()}>Find original saved result</button></div>}
    {!navigator.locks && <p role="alert">Saved request coordination is unavailable in this window. You can still reopen saved studies.</p>}
    {(error || storageError) && <p className="candle-error" role="alert">{storageError ?? error}</p>}
    {notice && <p className="candle-notice" role="status">{notice}</p>}
    {shown?.status === "completed" ? <StudyResult key={shown.id} run={shown} /> : run && run.status !== "completed" ? <p role="status">Saved study #{run.id} · {run.symbol} · {title(run.status)}. {run.error ?? "No completed analysis is available."}<button type="button" disabled={busy} onClick={() => void open(run.id)}>Reopen saved result</button></p> : <p className="candle-empty">{busy ? "Reading this study…" : "Choose an interval and load a study, or reopen its saved receipt."}</p>}
    <details className="candle-saved"><summary>Saved candle studies in the current history page</summary>{savedRuns.filter(item => item.tool === "candle_patterns").map(item => <button type="button" key={item.id} disabled={busy} onClick={() => void open(item.id)}>
      <span>#{item.id} · {item.symbol} · {stamp(item.started * 1000)} MT</span><span>{title(item.status)}</span></button>)}
      {!savedRuns.some(item => item.tool === "candle_patterns") && <p>No candle studies are listed on this saved-runs page. Older pages remain available in Research tools below.</p>}</details>
  </section>;
}
