import { useEffect, useMemo, useRef, useState } from "react";
import { CandlestickSeries, ColorType, CrosshairMode, HistogramSeries, LineSeries,
  createChart, createSeriesMarkers, type IChartApi, type ISeriesApi, type ISeriesMarkersPluginApi, type Time, type UTCTimestamp } from "lightweight-charts";
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
export type CandleChartAnalysis = Analysis;
export type ScannerChartFocus = { timeframe: Frame; atMs: number; levelId?: string; nonce: number;
  kind?: "levels" | "patterns" | "alerts"; seq?: number };
type ScannerLevel = { seq: number; id: string; kind: string; price: string; low: string; high: string;
  confirmed_at_ms: number; first_usable_ms: number; segment: number; validation: string; usable_until_ms?: number };
type ScannerEvent = Pattern & { seq: number; historical: boolean; bar_close_ms: number;
  evaluation?: { status: string; checks: Record<string, boolean | null>; unknowns: string[];
    evaluated_at: number; criteria: string; limitations: string[] } };
type OverlayPage<T> = { rows: T[]; total: number; next_before: number | null };
type ScannerView = { version: string; campaign_id: string; symbol: string; timeframe: Frame; seconds: number;
  observed_at: number; mode: "latest" | "historical"; processed_through_ms: number | null;
  candles: Candle[]; indicators: { points: Point[] }; levels: OverlayPage<ScannerLevel>;
  patterns: OverlayPage<ScannerEvent>; alerts: OverlayPage<ScannerEvent>;
  coverage: { state: string; input_candles: number; actual_start_ms: number | null; actual_end_ms: number | null;
    requested_start_ms: number | null; requested_end_ms: number | null; missing_candles: number;
    segments: number; segment_spans: { start_ms: number; end_ms: number; scanner_segment: number | null }[]; latest_segment_candles: number;
    warmup: Record<string, boolean>; source_available: boolean; source_error: string | null;
    scanner_status: string; scanner_error: string | null; scanner_observed_bars: number;
    scanner_expected_bars: number; scanner_missing_bars: number; pending: boolean;
    selected_at_ms: number | null; selected_candle_available: boolean | null };
  gaps: unknown[]; pagination: { next_before_ms: number | null };
  source: { kind: string; rows_sha256: string; progress_sha256: string; recognition_source_sha256: string;
    implementation_sha256: string; references: string[]; archive_verified: boolean };
  parameters: Record<string, unknown>; limitations: string[]; financial_authority: false;
  selection: null | { kind: "levels" | "patterns" | "alerts"; record: ScannerLevel | ScannerEvent;
    known_by_window_end: boolean; candle_available: boolean } };
type ChartQuery = { at_ms?: number; before_ms?: number; levels_before?: number; patterns_before?: number;
  alerts_before?: number; expected_progress_sha256?: string; selected_kind?: "levels" | "patterns" | "alerts"; selected_seq?: number };
type ScannerCard = { view: ScannerView | null; loading: boolean; error: string | null;
  query: ChartQuery; viewQuery: ChartQuery };
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

function patternMarkersFor(patterns: Pattern[], selected: number | null) {
  const grouped = new Map<number, Pattern[]>();
  for (const pattern of patterns) grouped.set(pattern.bar_open_ms, [...(grouped.get(pattern.bar_open_ms) ?? []), pattern]);
  return [...grouped.entries()].map(([time, events]) => ({ time: (time / 1000) as UTCTimestamp,
    position: "aboveBar" as const, shape: "circle" as const,
    color: events.some(event => event.volume_confirmed === true) ? "#f8c66a" : "#b3bfc7",
    text: time === selected ? `${[...new Set(events.map(event => title(event.kind)))].join(" · ")}${events.length > 1 ? ` (${events.length})` : ""}` : events.length > 1 ? String(events.length) : "" }));
}

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

export function CandleStudyChart({ analysis, selected, onSelect, compact = false, scannerLevels }: {
  analysis: Analysis; selected: number | null; onSelect: (time: number) => void; compact?: boolean;
  scannerLevels?: ScannerLevel[];
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
  const patternMarkers = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const timeline = useRef<number[]>([]);
  useEffect(() => {
    if (!host.current) return;
    let instance: IChartApi | null = null;
    try {
      instance = createChart(host.current, {
        autoSize: true, height: compact ? 290 : 390,
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
      const gaps = data.flatMap((bar, i) => i > 0 ? Array.from({ length: scannerLevels ?
        (bar.time > data[i - 1].time + analysis.seconds ? 1 : 0) : Math.max(0,
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
      const overlaySegments: { id: string; from: number; to: number; price: string }[] = [];
      if (levels && scannerLevels) for (const zone of scannerLevels) {
        const usable = analysis.candles.filter(bar => bar.open_ms >= zone.first_usable_ms &&
          (zone.usable_until_ms == null || bar.open_ms < zone.usable_until_ms));
        const segments: Candle[][] = [];
        for (const bar of usable) {
          if (!segments.length || bar.open_ms !== segments.at(-1)!.at(-1)!.open_ms + analysis.seconds * 1000) segments.push([]);
          segments.at(-1)!.push(bar);
        }
        for (const segment of segments) for (const [boundary, price] of [["low", zone.low], ["price", zone.price], ["high", zone.high]]) {
          const line = instance.addSeries(LineSeries, { color: zone.kind === "support" ? "#7ed4b3a0" : "#eda89ca0",
            lineWidth: 1, lineStyle: 2, lastValueVisible: false, priceLineVisible: false,
            crosshairMarkerVisible: false });
          const endpoints = segment.length > 1 ? [segment[0], segment.at(-1)!] : segment;
          line.setData(endpoints.map(bar => ({ time: (bar.open_ms / 1000) as UTCTimestamp, value: Number(price) })));
          overlaySegments.push({ id: `${zone.id}:${boundary}`, from: segment[0].open_ms,
            to: segment.at(-1)!.open_ms, price });
        }
      }
      host.current.dataset.levelSegments = JSON.stringify(overlaySegments);
      host.current.dataset.levelIds = JSON.stringify(levels ? scannerLevels?.map(level => level.id) ?? analysis.zones.slice(-30).map(level => level.id) : []);
      if (levels && !scannerLevels) for (const zone of analysis.zones.slice(-30)) candles.createPriceLine({
        price: Number(zone.price), color: zone.kind.includes("support") ? "#7ed4b380" : "#eda89c80", lineWidth: 1,
        lineStyle: 2, axisLabelVisible: false, title: title(zone.kind),
      });
      const markers = patternMarkersFor(analysis.patterns, null).sort((a, b) => a.time - b.time);
      patternMarkers.current = createSeriesMarkers(candles, markers);
      host.current.dataset.patternIds = JSON.stringify(analysis.patterns.map(pattern => pattern.id));
      host.current.dataset.markerCount = String(markers.length);
      host.current.dataset.patternCount = String(analysis.patterns.length);
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
    return () => { instance?.remove(); chart.current = null; patternMarkers.current = null; lines.current = {}; timeline.current = []; };
  }, [analysis, levels, compact, scannerLevels]);
  useEffect(() => {
    for (const key of Object.keys(colors) as Indicator[]) for (const line of lines.current[key] ?? []) line.applyOptions({ visible: enabled.includes(key) });
  }, [enabled]);
  useEffect(() => {
    patternMarkers.current?.setMarkers(patternMarkersFor(analysis.patterns, selected).sort((a, b) => a.time - b.time));
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
  }, [selected, analysis, levels]);
  return <div className="candle-study-chart">
    <div className="candle-chart-controls" role="group" aria-label="Candle chart overlays">
      {(Object.keys(colors) as Indicator[]).map(key => <button key={key} type="button" aria-pressed={enabled.includes(key)}
        style={{ borderColor: colors[key] }} onClick={() => setEnabled(old => old.includes(key) ? old.filter(k => k !== key) : [...old, key])}>{labels[key]}</button>)}
      <button type="button" aria-pressed={levels} onClick={() => setLevels(!levels)}>Level zones</button>
      <button type="button" onClick={() => chart.current?.timeScale().fitContent()}>Fit saved history</button>
    </div>
    {chartError && <p role="alert">{chartError}</p>}
    <div ref={host} className={`candle-chart-host${compact ? " candle-chart-host-compact" : ""}`} role="img" aria-label={`${analysis.symbol} closed ${analysis.timeframe} candles with volume, SMA 10, 50, 100 and 50-candle VWAP`} />
    <p className="candle-help">Drag to pan; scroll or pinch to zoom. Dots mark recorded patterns; selecting their candle reveals its name. Chart axis UTC; inspection and crosshair Mountain time. Missing intervals stay empty, and indicators restart after contiguous warmup. Level confirmation times and original reasons are in the chart details.</p>
    <p className="chart-attribution"><a href="https://www.tradingview.com/" target="_blank" rel="noreferrer">TradingView Lightweight Charts™</a> · Copyright © 2025 TradingView, Inc.</p>
  </div>;
}

function StudyResult({ run, compact = false, expanded = true, onExpand }: {
  run: Run; compact?: boolean; expanded?: boolean; onExpand?: () => void;
}) {
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
    {compact && <p className="candle-source">{analysis.source} · SMA 10 / 50 / 100 and 50-candle VWAP · {windows[analysis.window]}</p>}
    <p className="candle-coverage"><strong>{coverage.bar_count.toLocaleString()} actual closed candles</strong> of {coverage.expected_bars.toLocaleString()} requested · {coverage.missing_bars.toLocaleString()} missing within the bounded retrieval.
      {coverage.truncated && <strong> Requested history was truncated to the bounded retrieval.</strong>}<br />
      Requested {stamp(coverage.requested_start_ms)} to {stamp(coverage.requested_end_ms)} MT. Returned {stamp(coverage.actual_start_ms)} to {stamp(coverage.actual_end_ms)} MT.<br />
      Latest contiguous segment: {coverage.latest_segment_candles.toLocaleString()} candles. {coverage.patterns_omitted_from_display > 0 && `${coverage.patterns_omitted_from_display.toLocaleString()} older pattern records are outside the retained display bound.`}</p>
    <CandleStudyChart analysis={analysis} selected={selected} onSelect={setSelected} compact={compact} />
    {compact && <div className="candle-pattern-summary" aria-label={`${analysis.timeframe} pattern summary`}>
      {Object.entries(analysis.patterns.reduce<Record<string, number>>((counts, item) => {
        counts[item.kind] = (counts[item.kind] ?? 0) + 1; return counts;
      }, {})).map(([kind, total]) => <span key={kind}>{title(kind)} <strong>{total}</strong></span>)}
      {!analysis.patterns.length && <span>No recorded pattern in this study</span>}
      <button type="button" aria-expanded={expanded} onClick={onExpand}>{expanded ? `Hide ${analysis.timeframe} details` : `Inspect ${analysis.timeframe} details`}</button>
    </div>}
    {(!compact || expanded) && <>
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
    </>}
  </div>;
}

function validateScannerView(value: ScannerView, campaignId: string, symbol: string, frame: Frame, query: ChartQuery) {
  const fail = () => { throw new Error("Saved scanner chart identity or coverage is incomplete. No fresh study was substituted."); };
  if (!value || value.version !== "saved-scanner-chart-v1" || value.campaign_id !== campaignId ||
      value.symbol !== symbol || value.timeframe !== frame || value.seconds !== frames[frame] ||
      value.financial_authority !== false || value.mode !== (query.at_ms !== undefined || query.before_ms !== undefined ? "historical" : "latest") ||
      !Number.isFinite(value.observed_at) || !Array.isArray(value.candles) || value.candles.length > 1000 ||
      !Array.isArray(value.indicators?.points) || value.indicators.points.length !== value.candles.length ||
      !value.source || typeof value.source.kind !== "string" || typeof value.source.archive_verified !== "boolean" ||
      !Array.isArray(value.source.references) || !value.source.references.every(item => typeof item === "string") ||
      ![value.source.rows_sha256, value.source.progress_sha256, value.source.recognition_source_sha256, value.source.implementation_sha256].every(hash => typeof hash === "string" && /^[a-f0-9]{64}$/.test(hash)) ||
      !Array.isArray(value.limitations) || !value.limitations.every(item => typeof item === "string")) fail();
  const step = frames[frame] * 1000;
  value.candles.forEach((bar, i) => {
    const point = value.indicators.points[i];
    if (!Number.isSafeInteger(bar.open_ms) || bar.open_ms % step !== 0 || bar.close_ms !== bar.open_ms + step - 1 ||
        ![bar.open, bar.high, bar.low, bar.close, bar.volume].every(finiteDecimal) || Number(bar.volume) < 0 ||
        Number(bar.low) <= 0 || Number(bar.low) > Math.min(Number(bar.open), Number(bar.close)) ||
        Number(bar.high) < Math.max(Number(bar.open), Number(bar.close)) ||
        i > 0 && bar.open_ms <= value.candles[i - 1].open_ms || point?.open_ms !== bar.open_ms ||
        ![point.sma10, point.sma50, point.sma100, point.vwap, point.volume_ratio].every(nullableDecimal)) fail();
  });
  for (const page of [value.levels, value.patterns, value.alerts]) {
    if (!page || !Array.isArray(page.rows) || page.rows.length > 100 || !count(page.total) || page.total < page.rows.length ||
        page.next_before !== null && !count(page.next_before) || page.rows.some(item => !count(item.seq) || typeof item.id !== "string")) fail();
  }
  const selectedLevel = value.selection?.kind === "levels" ? value.selection.record as ScannerLevel : undefined;
  const selectedEvent = value.selection && value.selection.kind !== "levels" ? value.selection.record as ScannerEvent : undefined;
  if (value.selection !== null && (!value.selection || !["levels", "patterns", "alerts"].includes(value.selection.kind) ||
      !count(value.selection.record?.seq) || typeof value.selection.record?.id !== "string" ||
      typeof value.selection.known_by_window_end !== "boolean" || typeof value.selection.candle_available !== "boolean")) fail();
  if (query.selected_kind !== undefined ? value.selection?.kind !== query.selected_kind || value.selection?.record.seq !== query.selected_seq : value.selection !== null) fail();
  if ([...value.levels.rows, ...(selectedLevel ? [selectedLevel] : [])].some(item => ![item.price, item.low, item.high].every(finiteDecimal) ||
      ![item.confirmed_at_ms, item.first_usable_ms].every(Number.isSafeInteger) || !count(item.segment) ||
      !["support", "resistance"].includes(item.kind) || item.first_usable_ms !== item.confirmed_at_ms + 1 ||
      Number(item.low) > Number(item.price) || Number(item.high) < Number(item.price))) fail();
  for (const item of [...value.patterns.rows, ...value.alerts.rows, ...(selectedEvent ? [selectedEvent] : [])]) if (!Number.isSafeInteger(item.bar_open_ms) ||
      typeof item.kind !== "string" || typeof item.level_id !== "string" || !finiteDecimal(item.level_price) ||
      !nullableDecimal(item.volume_ratio) || ![true, false, null].includes(item.volume_confirmed) ||
      typeof item.reason !== "string" || typeof item.historical !== "boolean" ||
      item.evaluation !== undefined && (!item.evaluation || typeof item.evaluation.status !== "string" ||
        !item.evaluation.checks || typeof item.evaluation.checks !== "object" || Array.isArray(item.evaluation.checks) ||
        !Object.values(item.evaluation.checks).every(check => check === null || check === true || check === false) ||
        !Array.isArray(item.evaluation.unknowns) || !item.evaluation.unknowns.every(unknown => typeof unknown === "string") ||
        !Number.isFinite(item.evaluation.evaluated_at) || typeof item.evaluation.criteria !== "string")) fail();
  const coverage = value.coverage;
  if (!coverage || coverage.input_candles !== value.candles.length || typeof coverage.source_available !== "boolean" ||
      coverage.selected_at_ms !== (query.at_ms ?? null) || typeof coverage.pending !== "boolean" ||
      ![coverage.actual_start_ms, coverage.actual_end_ms, coverage.requested_start_ms, coverage.requested_end_ms].every(time => time === null || Number.isSafeInteger(time)) ||
      ![coverage.input_candles, coverage.missing_candles, coverage.latest_segment_candles,
        coverage.scanner_observed_bars, coverage.scanner_expected_bars, coverage.scanner_missing_bars].every(count) ||
      !Array.isArray(coverage.segment_spans) || coverage.segment_spans.some(span =>
        !Number.isSafeInteger(span.start_ms) || !Number.isSafeInteger(span.end_ms) || span.end_ms < span.start_ms ||
        span.scanner_segment !== null && !count(span.scanner_segment)) ||
      !value.pagination || value.pagination.next_before_ms !== null && !count(value.pagination.next_before_ms)) fail();
  if (value.candles.length && (coverage.actual_start_ms !== value.candles[0].open_ms || coverage.actual_end_ms !== value.candles.at(-1)!.close_ms) ||
      !value.candles.length && (coverage.actual_start_ms !== null || coverage.actual_end_ms !== null) ||
      query.expected_progress_sha256 !== undefined && value.source.progress_sha256 !== query.expected_progress_sha256) fail();
}

function ScannerCardView({ frame, card, selection, expanded, onExpand, onRead, onSelect, onEvent }: {
  frame: Frame; card: ScannerCard; selection: number | null; expanded: boolean;
  onExpand: () => void; onRead: (query: ChartQuery) => void; onSelect: (time: number | null) => void;
  onEvent: (event: ScannerEvent) => void;
}) {
  const view = card.view;
  const plot = useMemo(() => {
    if (!view) return null;
    const visible = new Set(view.candles.map(bar => bar.open_ms));
    const events = [...view.patterns.rows, ...view.alerts.rows];
    const originalSelection = view.selection?.kind !== "levels" ? view.selection?.record as ScannerEvent | undefined : undefined;
    if (originalSelection && !events.some(item => item.id === originalSelection.id)) events.push(originalSelection);
    const originalLevels = [...view.levels.rows];
    if (view.selection?.kind === "levels" && !originalLevels.some(level => level.id === view.selection!.record.id)) originalLevels.push(view.selection.record as ScannerLevel);
    const levels = originalLevels.flatMap(level => view.coverage.segment_spans.flatMap(span => {
      const confirmedHere = level.confirmed_at_ms >= span.start_ms && level.confirmed_at_ms <= span.end_ms;
      const continuityKnown = level.confirmed_at_ms < span.start_ms && span.scanner_segment === level.segment;
      if (!confirmedHere && !continuityKnown || level.first_usable_ms > span.end_ms) return [];
      return [{ ...level, first_usable_ms: Math.max(level.first_usable_ms, span.start_ms),
        usable_until_ms: span.end_ms + 1 }];
    }));
    const analysis: Analysis = { version: view.version, symbol: view.symbol, timeframe: frame, window: "recent",
      seconds: view.seconds, source: view.source.kind, observed_at: view.observed_at,
      candles: view.candles, indicators: view.indicators, zones: [], patterns: events.filter(item => visible.has(item.bar_open_ms)),
      parameters: view.parameters, limitations: view.limitations,
      coverage: { requested_start_ms: view.coverage.requested_start_ms ?? 0, requested_end_ms: view.coverage.requested_end_ms ?? 0,
        actual_start_ms: view.coverage.actual_start_ms ?? 0, actual_end_ms: view.coverage.actual_end_ms ?? 0,
        bar_count: view.candles.length, expected_bars: view.candles.length + view.coverage.missing_candles,
        missing_bars: view.coverage.missing_candles, truncated: false, patterns_observed: view.patterns.total + view.alerts.total,
        patterns_omitted_from_display: 0, latest_segment_candles: view.coverage.latest_segment_candles } };
    return { analysis, levels };
  }, [view, frame]);
  const bar = selection === null ? view?.candles.at(-1) : view?.candles.find(item => item.open_ms === selection);
  const point = view?.indicators.points.find(item => item.open_ms === bar?.open_ms);
  const originalSelection = view?.selection?.kind !== "levels" ? view?.selection?.record as ScannerEvent | undefined : undefined;
  const chosenEvent = originalSelection;
  const events = [...(view?.patterns.rows ?? []), ...(view?.alerts.rows ?? [])].sort((a, b) => b.bar_open_ms - a.bar_open_ms);
  const candleEvents = [...events];
  if (chosenEvent && !candleEvents.some(event => event.id === chosenEvent.id)) candleEvents.push(chosenEvent);
  return <article className="candle-chart-card" aria-label={`${frame} scanner chart`} data-timeframe={frame}>
    <header><h4>{frame} · {view?.symbol ?? "saved scanner"}</h4><button type="button" aria-expanded={expanded} onClick={onExpand}>{expanded ? `Hide ${frame} details` : `Inspect ${frame} details`}</button></header>
    <div className="candle-actions"><button type="button" disabled={card.loading || !view?.pagination.next_before_ms}
      onClick={() => onRead({ before_ms: view!.pagination.next_before_ms! })}>Older saved candles</button>
      <button type="button" disabled={card.loading} onClick={() => { onSelect(null); onRead({}); }}>Latest saved candles</button></div>
    {card.loading && <p role="status">Reading {frame} saved scanner candles…</p>}
    {card.error && <p role="alert" className="candle-error">{card.error}{view && " The last successful window remains visible below."}</p>}
    {view && <p className="candle-coverage"><strong>{view.candles.length} recorded closed candles · {title(view.mode)}</strong><br />
      {view.candles.length ? `${stamp(view.candles[0].open_ms)} to ${stamp(view.candles.at(-1)!.close_ms)} MT` : "No recorded candles in this saved window."}<br />
      {view.coverage.missing_candles} missing candles in this window; latest contiguous warmup {view.coverage.latest_segment_candles} candles.<br />
      Scanner scope: {view.coverage.scanner_observed_bars.toLocaleString()} observed / {view.coverage.scanner_expected_bars.toLocaleString()} expected · {view.coverage.scanner_missing_bars.toLocaleString()} missing · {title(view.coverage.scanner_status)}{view.coverage.pending && " · partial page processing retained"}.
      {(view.coverage.source_error || view.coverage.scanner_error) && <span className="candle-error"> {view.coverage.source_error ?? view.coverage.scanner_error}</span>}</p>}
    {plot && view?.candles.length ? <CandleStudyChart analysis={plot.analysis} selected={selection} onSelect={onSelect} compact scannerLevels={plot.levels} /> :
      <div className="candle-chart-placeholder"><p>{card.loading ? "Reading this saved frame…" : view ? "No saved candles available here. Missing or unprepared history is not an empty successful analysis." : "A prepared scanner campaign is needed for saved candles."}</p></div>}
    {view && <><div className="candle-pattern-summary" aria-label={`${frame} saved pattern counts`}>
      <span>Historical patterns <strong>{view.patterns.total}</strong></span><span>Prospective alerts <strong>{view.alerts.total}</strong></span><span>Support/resistance levels <strong>{view.levels.total}</strong></span>
      {Object.entries(events.reduce<Record<string, number>>((result, event) => { result[event.kind] = (result[event.kind] ?? 0) + 1; return result; }, {})).map(([kind, total]) => <span key={kind}>{title(kind)} <strong>{total} on loaded pages</strong></span>)}</div>
      <p className="candle-help">Display SMAs use 10/50/100 candles of this frame. VWAP is a trailing 50-candle HLC3 approximation. These readings describe the saved window; the original recognition uses confirmed levels and volume, and does not establish a VWAP trading edge.</p>
      {expanded && <><section className="candle-inspector" aria-label={`${frame} saved candle inspection`}>
        <h4>{bar ? `${stamp(bar.open_ms)} MT · ${frame} closed candle` : selection !== null ? `${stamp(selection)} MT · selected candle unavailable` : "No recorded candle"}</h4>
        {bar && <div className="candle-metrics"><span>Open <strong>{decimal(bar.open)}</strong></span><span>High <strong>{decimal(bar.high)}</strong></span><span>Low <strong>{decimal(bar.low)}</strong></span><span>Close <strong>{decimal(bar.close)}</strong></span><span>Volume <strong>{decimal(bar.volume)}</strong></span>
          <span>Volume / prior median <strong>{point?.volume_ratio == null ? "Unavailable" : `${decimal(point.volume_ratio)}×`}</strong></span>
          {(Object.keys(colors) as Indicator[]).map(key => <span key={key} style={{ color: colors[key] }}>{labels[key]}<strong>{decimal(point?.[key])}</strong>
            <small>{bar && point?.[key] != null ? Number(bar.close) > Number(point[key]) ? "Close above" : Number(bar.close) < Number(point[key]) ? "Close below" : "Close at" : "Insufficient contiguous warmup"}</small></span>)}</div>}
        {!bar && <p>No OHLC, volume or indicator value is assigned to this missing interval.</p>}
        {candleEvents.filter(event => event.bar_open_ms === bar?.open_ms).map(event => <p key={`${event.historical}:${event.seq}`}><strong>{title(event.kind)}</strong> · level {decimal(event.level_price)}: {event.reason}</p>)}</section>
        <div className="candle-pattern-grid"><section aria-label={`${frame} original patterns`}><h4>Original recognized moves</h4>
          <p>{view.patterns.rows.length} historical pattern rows and {view.alerts.rows.length} alert rows on these pages. Only events whose candle is in this window are marked.</p>
          <div className="candle-pattern-list">{events.map(event => <button type="button" key={`${event.historical ? "history" : "alert"}:${event.seq}`} aria-pressed={chosenEvent?.id === event.id}
            onClick={() => onEvent(event)}><strong>{title(event.kind)}</strong><time>{stamp(event.bar_open_ms)} MT</time><span>{event.historical ? "Historical description" : `Prospective alert · ${title(event.evaluation?.status ?? "evaluation unavailable")}`} · level {decimal(event.level_price)}</span></button>)}</div>
          {!events.length && <p>No original event on these saved pages.</p>}
          <div className="candle-actions">{(["patterns", "alerts"] as const).map(kind => <button key={kind} type="button" disabled={card.loading || !!card.error || view[kind].next_before == null}
            onClick={() => onRead({ ...card.viewQuery, [`${kind}_before`]: view[kind].next_before!, expected_progress_sha256: view.source.progress_sha256 })}>Older {kind}</button>)}</div></section>
          <section className="candle-pattern-detail" aria-label={`${frame} original recognition explanation`}><h4>{chosenEvent ? title(chosenEvent.kind) : "Choose an original move"}</h4>
            {chosenEvent ? <><p>{chosenEvent.reason}</p><p>{stamp(chosenEvent.bar_open_ms)} MT · recorded level {decimal(chosenEvent.level_price)} · original volume {chosenEvent.volume_ratio == null ? "unknown" : `${decimal(chosenEvent.volume_ratio)}×`}.
              Volume confirmation {chosenEvent.volume_confirmed === null ? "unknown" : chosenEvent.volume_confirmed ? "present" : "absent"}.</p>
              {view.selection && !view.selection.candle_available && <p>The exact saved event is retained, but its candle is missing from this source page. No neighboring candle was substituted.</p>}
              {chosenEvent.evaluation ? <><p>Original current-candidate evaluation: <strong>{title(chosenEvent.evaluation.status)}</strong> · {stamp(chosenEvent.evaluation.evaluated_at * 1000)} MT.</p>
                <ul>{Object.entries(chosenEvent.evaluation.checks).map(([name, value]) => <li key={name}>{title(name)}: {value === null ? "unknown" : value ? "met" : "not met"}</li>)}</ul>
                <ul>{chosenEvent.evaluation.unknowns.map((unknown, i) => <li key={i}>{unknown}</li>)}</ul><p>{chosenEvent.evaluation.criteria}</p></> : <p>No prospective evaluation was recorded for this historical description.</p>}</> : <p>Select a saved event to reopen its original candle window and reason. Unknown inputs remain unknown.</p>}</section></div>
        <section aria-label={`${frame} saved alert zones`}><h4>Horizontal support/resistance alert zones · {view.levels.rows.length} of {view.levels.total}</h4>
          <p>Lines start after original confirmation, within verified contiguous history. A level with unknown continuity is listed without extending its line across a gap.</p>
          {view.selection?.kind === "levels" && <p className="candle-pattern-detail">Selected original {title((view.selection.record as ScannerLevel).kind)} level {decimal((view.selection.record as ScannerLevel).price)} · zone {decimal((view.selection.record as ScannerLevel).low)} – {decimal((view.selection.record as ScannerLevel).high)}.<br />
            First usable {stamp((view.selection.record as ScannerLevel).first_usable_ms)} MT. {view.selection.known_by_window_end ? "Already confirmed by this window’s end." : "Not yet known at this window’s end; no earlier alert line is drawn."}</p>}
          <div className="candle-pattern-list">{view.levels.rows.map(level => <button key={level.seq} type="button" onClick={() => { onSelect(level.first_usable_ms); onRead({ at_ms: Math.min(level.first_usable_ms, view.processed_through_ms ?? level.confirmed_at_ms), selected_kind: "levels", selected_seq: level.seq }); }}>
            <strong>{title(level.kind)} · {decimal(level.price)}</strong><span>Zone {decimal(level.low)} – {decimal(level.high)} · first usable {stamp(level.first_usable_ms)} MT</span></button>)}</div>
          <button type="button" disabled={card.loading || !!card.error || view.levels.next_before == null} onClick={() => onRead({ ...card.viewQuery, levels_before: view.levels.next_before!, expected_progress_sha256: view.source.progress_sha256 })}>Older levels</button></section>
        <details><summary>Saved source and coverage</summary><p>{view.source.kind} · archive verification {view.source.archive_verified ? "verified" : "not established"} · read {stamp(view.observed_at * 1000)} MT.</p>
          <p>Display indicator recomputation is separate from original scanner recognition. No orders, strategy approval or measured profitability follows.</p>
          <ul>{view.limitations.map((item, i) => <li key={i}>{item}</li>)}</ul><p className="candle-source">Saved rows {view.source.rows_sha256}<br />Original recognition {view.source.recognition_source_sha256}</p></details></>}
    </>}
  </article>;
}

export function ScannerChartGrid({ campaignId, symbol, focus }: {
  campaignId: string | null; symbol: string; focus: ScannerChartFocus | null;
}) {
  const blank = (): Record<Frame, ScannerCard> => Object.fromEntries((Object.keys(frames) as Frame[]).map(frame => [frame,
    { view: null, loading: false, error: null, query: {}, viewQuery: {} }])) as Record<Frame, ScannerCard>;
  const [cards, setCards] = useState(blank);
  const [expanded, setExpanded] = useState<Frame | null>(null);
  const [selected, setSelected] = useState<Partial<Record<Frame, number | null>>>({});
  const [bookmarkError, setBookmarkError] = useState<string | null>(null);
  const latestBookmarkError = useRef(bookmarkError); latestBookmarkError.current = bookmarkError;
  const latestCards = useRef(cards); latestCards.current = cards;
  const scope = `${campaignId}:${symbol}`;
  const displayedScope = useRef(scope);
  const generation = useRef(0);
  const serials = useRef<Partial<Record<Frame, number>>>({});
  const active = useRef(new Map<Frame, AbortController>());
  const queue = useRef<{ frame: Frame; query: ChartQuery; campaign: string; symbol: string; generation: number; serial: number }[]>([]);
  const pump = useRef<() => void>(() => {});
  const scopeRef = useRef(scope); scopeRef.current = scope;
  const readyScope = displayedScope.current === scope;

  pump.current = () => {
    while (active.current.size < 2 && queue.current.length) {
      const next = queue.current.findIndex(job => !active.current.has(job.frame));
      if (next < 0) break;
      const job = queue.current.splice(next, 1)[0];
      if (job.generation !== generation.current || job.serial !== serials.current[job.frame]) continue;
      const controller = new AbortController(); active.current.set(job.frame, controller);
      const timeout = setTimeout(() => controller.abort(), 30000);
      const params = new URLSearchParams({ campaign_id: job.campaign, symbol: job.symbol, timeframe: job.frame });
      for (const [key, value] of Object.entries(job.query)) if (value !== undefined) params.set(key, String(value));
      const current = () => job.generation === generation.current && job.serial === serials.current[job.frame] && `${job.campaign}:${job.symbol}` === scopeRef.current;
      void (async () => {
        try {
          const response = await fetch(`/api/research/pattern-scanner/chart?${params}`, { cache: "no-store", signal: controller.signal });
          if (!response.ok) throw new Error(`Saved ${job.frame} scanner chart unavailable (${response.status}). No fresh study was requested.`);
          const view = await response.json() as ScannerView;
          validateScannerView(view, job.campaign, job.symbol, job.frame, job.query);
          if (current()) {
            const pinnedQuery = view.mode === "historical" ? { ...job.query, expected_progress_sha256: view.source.progress_sha256 } : job.query;
            setCards(old => ({ ...old, [job.frame]: { view, loading: false, error: null, query: pinnedQuery, viewQuery: pinnedQuery } }));
            if (view.mode === "historical") {
              const saved = new URLSearchParams(location.hash.split("?")[1] ?? "");
              if (saved.get("scanner_campaign") === job.campaign && saved.get("symbol") === job.symbol &&
                  saved.get("scanner_chart_frame") === job.frame &&
                  saved.get("scanner_chart_at_ms") === (job.query.at_ms === undefined ? null : String(job.query.at_ms)) &&
                  saved.get("scanner_chart_before_ms") === (job.query.before_ms === undefined ? null : String(job.query.before_ms))) {
                saved.set("scanner_chart_progress_sha256", view.source.progress_sha256);
                history.replaceState(null, "", `#markets?${saved}`);
              }
            }
          }
        } catch (cause) {
          if (current()) setCards(old => ({ ...old, [job.frame]: { ...old[job.frame], loading: false,
            error: controller.signal.aborted ? "This saved read timed out or was canceled. Its original data was not replaced." : cause instanceof Error ? cause.message : "Saved chart unavailable." } }));
        } finally {
          clearTimeout(timeout);
          if (active.current.get(job.frame) === controller) active.current.delete(job.frame);
          pump.current();
        }
      })();
    }
  };
  function read(frame: Frame, query: ChartQuery = {}) {
    if (!campaignId || !/^patterns-[a-f0-9]{24}$/.test(campaignId) || !/^[A-Z0-9]{3,24}$/.test(symbol)) return;
    const serial = (serials.current[frame] ?? 0) + 1; serials.current[frame] = serial;
    queue.current = queue.current.filter(job => job.frame !== frame);
    active.current.get(frame)?.abort();
    queue.current.push({ frame, query, campaign: campaignId, symbol, generation: generation.current, serial });
    setCards(old => ({ ...old, [frame]: { ...old[frame], loading: true, error: null, query } }));
    pump.current();
  }
  useEffect(() => {
    generation.current++; queue.current = []; serials.current = {};
    for (const controller of active.current.values()) controller.abort();
    displayedScope.current = scope; setCards(blank()); setSelected({}); setExpanded(null);
    const restore = () => { if (campaignId) {
      const params = new URLSearchParams(location.hash.split("?")[1] ?? "");
      const rememberedFrame = params.get("scanner_chart_frame") as Frame;
      const rememberedAt = params.get("scanner_chart_at_ms");
      const rememberedBefore = params.get("scanner_chart_before_ms");
      if (params.get("symbol") !== symbol || params.get("scanner_campaign") !== campaignId) {
        if (params.has("scanner_chart_frame")) return;
      }
      const kind = params.get("scanner_chart_kind");
      const seq = params.get("scanner_chart_seq");
      const exactRecord = kind !== null && ["levels", "patterns", "alerts"].includes(kind) && seq !== null && /^\d+$/.test(seq) && Number.isSafeInteger(Number(seq)) && Number(seq) > 0;
      const safeTime = (value: string | null) => value === null || /^\d+$/.test(value) && Number.isSafeInteger(Number(value));
      const restored = params.has("scanner_chart_frame");
      const query: ChartQuery = { ...(rememberedAt !== null ? { at_ms: Number(rememberedAt) } : {}),
        ...(rememberedBefore !== null ? { before_ms: Number(rememberedBefore) } : {}),
        ...(exactRecord ? { selected_kind: kind as "levels" | "patterns" | "alerts", selected_seq: Number(seq) } : {}) };
      let badCursor = false;
      for (const key of ["levels_before", "patterns_before", "alerts_before"] as const) {
        const cursor = params.get(`scanner_chart_${key}`);
        if (!safeTime(cursor)) badCursor = true;
        if (cursor !== null) query[key] = Number(cursor);
      }
      const progress = params.get("scanner_chart_progress_sha256");
      if (progress !== null) query.expected_progress_sha256 = progress;
      if (restored && (!Object.hasOwn(frames, rememberedFrame) || !safeTime(rememberedAt) || !safeTime(rememberedBefore) ||
          rememberedAt !== null && rememberedBefore !== null || (kind !== null || seq !== null) && !exactRecord ||
          badCursor || progress !== null && !/^[a-f0-9]{64}$/.test(progress) ||
          [query.levels_before, query.patterns_before, query.alerts_before].some(value => value !== undefined && value > 0) && !progress)) {
        setBookmarkError("The saved chart link has invalid scope or pagination. No latest window was substituted. Choose Latest saved candles to read a new window."); return;
      }
      setBookmarkError(null);
      for (const frame of Object.keys(frames) as Frame[]) read(frame, restored && frame === rememberedFrame ? query : {});
      if (restored) { setSelected({ [rememberedFrame]: rememberedAt === null ? null : Number(rememberedAt) }); setExpanded(rememberedFrame); }
      else { setSelected({}); setExpanded(null); }
    } };
    restore(); addEventListener("hashchange", restore); addEventListener("popstate", restore);
    return () => { generation.current++; queue.current = []; for (const controller of active.current.values()) controller.abort(); removeEventListener("hashchange", restore); removeEventListener("popstate", restore); };
  }, [scope]);
  useEffect(() => {
    const interval = setInterval(() => {
      if (document.hidden || !campaignId || latestBookmarkError.current || displayedScope.current !== scopeRef.current) return;
      for (const frame of Object.keys(frames) as Frame[]) {
        const card = latestCards.current[frame];
        if (!card.loading && Object.keys(card.query).length === 0) read(frame);
      }
    }, 30000);
    return () => clearInterval(interval);
  }, [scope]);
  function bookmark(frame: Frame, query: ChartQuery) {
    const params = new URLSearchParams(location.hash.split("?")[1] ?? "");
    for (const key of [...params.keys()]) if (key.startsWith("scanner_chart_")) params.delete(key);
    if (Object.keys(query).length && campaignId) {
      params.set("scanner_campaign", campaignId); params.set("scanner_chart_frame", frame);
      for (const [key, value] of Object.entries(query)) params.set(`scanner_chart_${key === "expected_progress_sha256" ? "progress_sha256" : key === "selected_kind" ? "kind" : key === "selected_seq" ? "seq" : key}`, String(value));
    }
    history.replaceState(null, "", `#markets?${params}`); setBookmarkError(null);
  }
  function choose(frame: Frame, atMs: number | null, record?: { kind: "levels" | "patterns" | "alerts"; seq: number }) {
    setSelected(old => ({ ...old, [frame]: atMs }));
    if (atMs !== null) bookmark(frame, { at_ms: atMs, ...(record ? { selected_kind: record.kind, selected_seq: record.seq } : {}) });
  }
  useEffect(() => {
    if (!focus || !campaignId || !Object.hasOwn(frames, focus.timeframe) || !Number.isSafeInteger(focus.atMs)) return;
    const record = focus.kind && focus.seq ? { kind: focus.kind, seq: focus.seq } : undefined;
    setExpanded(focus.timeframe); choose(focus.timeframe, focus.atMs, record); read(focus.timeframe, { at_ms: focus.atMs,
      ...(record ? { selected_kind: record.kind, selected_seq: record.seq } : {}) });
  }, [focus?.nonce]);
  return <section id="scanner-chart-grid" className="candle-workspace scanner-chart-workspace" aria-label="Saved scanner pattern charts">
    <header><div><p className="station-kicker">SAVED SCANNER FINDINGS · FIVE NATIVE FRAMES</p><h3>{symbol.replace(/USD$/, " / USD")} pattern charts</h3></div><span>Descriptive · no order authority</span></header>
    <p className="candle-intro">Candles, recognized moves and horizontal support/resistance alert zones from this scanner campaign. Inspect an event to see its original explanation alongside available moving averages, VWAP and volume. Historical recognition is not validated profitability.</p>
    <p className="candle-help">Latest saved windows refresh every 30 seconds while this view is visible, with at most two reads at a time. Historical and paged windows stay pinned until you choose a different window.</p>
    {bookmarkError && <p className="candle-error" role="alert">{bookmarkError}</p>}
    <button type="button" disabled={!campaignId} onClick={() => { if (bookmarkError) bookmark("5m", {}); for (const frame of Object.keys(frames) as Frame[]) if (!latestCards.current[frame].loading && Object.keys(latestCards.current[frame].query).length === 0) read(frame); }}>Refresh latest saved charts</button>
    {!campaignId && <p role="status">No scanner campaign is prepared. All five frames remain visible; saved candles will appear after their scope has actually been processed.</p>}
    <div className="candle-chart-grid">{(Object.keys(frames) as Frame[]).map(frame => <ScannerCardView key={`${scope}:${frame}`} frame={frame}
      card={readyScope ? cards[frame] : blank()[frame]} selection={selected[frame] ?? null}
      expanded={expanded === frame} onExpand={() => setExpanded(old => old === frame ? null : frame)} onRead={query => { bookmark(frame, query); if (!Object.hasOwn(query, "selected_seq")) setSelected(old => ({ ...old, [frame]: null })); read(frame, query); }}
      onSelect={atMs => setSelected(old => ({ ...old, [frame]: atMs }))} onEvent={event => { const kind = event.historical ? "patterns" : "alerts";
        setExpanded(frame); choose(frame, event.bar_open_ms, { kind, seq: event.seq });
        read(frame, { at_ms: event.bar_open_ms, selected_kind: kind, selected_seq: event.seq }); }} />)}</div>
  </section>;
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
