import { memo, useEffect, useRef, useState } from "react";
import "./market-chart.css";
import { CandlestickSeries, ColorType, CrosshairMode, HistogramSeries, LineSeries, createChart,
  type IChartApi, type ISeriesApi, type UTCTimestamp } from "lightweight-charts";

export type Candle = { open_ms: number; close_ms: number; open: string; high: string; low: string; close: string; volume: string };
type Point = { open_ms: number; sma: string | null; ema: string | null; bb_upper: string | null; bb_lower: string | null; vwap: string | null };
export type Indicators = { period: number; vwap_anchor_ms: number | null; points: Point[] };
const colors = { ema: "#63b3ff", sma: "#f8c66a", vwap: "#d291ff", bb_upper: "#91a4bd", bb_lower: "#91a4bd" };
type Key = keyof typeof colors;
const localTime = (ms: number) => new Date(ms).toLocaleTimeString([], { timeZone: "America/Denver", hour: "2-digit", minute: "2-digit" });
const value = (v: string | undefined | null) => v == null ? "Unavailable" : Number(v).toLocaleString("en-US", { maximumFractionDigits: 8 });

export const MarketChart = memo(function MarketChart({ bars, range, indicators, stale, symbol }: {
  bars: Candle[]; range: number; indicators?: Indicators; stale: boolean; symbol: string;
}) {
  const host = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const candleSeries = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeries = useRef<ISeriesApi<"Histogram"> | null>(null);
  const lines = useRef<Partial<Record<Key, ISeriesApi<"Line">>>>({});
  const latest = useRef(bars);
  const prior = useRef<{ symbol: string; range: number; last: number }>({ symbol: "", range: 0, last: 0 });
  const [selected, setSelected] = useState<Candle | null>(null);
  const [enabled, setEnabled] = useState<Key[]>([]);
  const [follow, setFollow] = useState(true);
  const followRef = useRef(follow);
  const [error, setError] = useState<string | null>(null);
  latest.current = bars;
  followRef.current = follow;
  useEffect(() => {
    if (!host.current) return;
    const instance = createChart(host.current, {
      autoSize: true, height: 330,
      layout: { background: { type: ColorType.Solid, color: "#0e1826" }, textColor: "#abc1dc", attributionLogo: true },
      grid: { vertLines: { color: "#223148" }, horzLines: { color: "#223148" } },
      crosshair: { mode: CrosshairMode.Normal },
      timeScale: { timeVisible: true, secondsVisible: false, rightOffset: 3, fixLeftEdge: false,
        tickMarkFormatter: (t: unknown) => localTime(Number(t) * 1000) },
      localization: { timeFormatter: (t: unknown) => new Date(Number(t) * 1000).toLocaleString("en-US", { timeZone: "America/Denver" }) },
    });
    chart.current = instance;
    candleSeries.current = instance.addSeries(CandlestickSeries, {
      upColor: "#26dfa0", downColor: "#f57581", wickUpColor: "#26dfa0", wickDownColor: "#f57581",
      borderVisible: false, priceScaleId: "right",
    });
    candleSeries.current.priceScale().applyOptions({ scaleMargins: { top: .08, bottom: .24 } });
    volumeSeries.current = instance.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "volume", lastValueVisible: false, priceLineVisible: false });
    volumeSeries.current.priceScale().applyOptions({ scaleMargins: { top: .8, bottom: 0 }, visible: false });
    for (const key of Object.keys(colors) as Key[]) lines.current[key] = instance.addSeries(LineSeries, {
      color: colors[key], lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
      crosshairMarkerVisible: false, visible: false,
    });
    instance.subscribeCrosshairMove(event => setSelected(event.time == null ? null : latest.current.find(b => b.open_ms === Number(event.time) * 1000) ?? null));
    return () => { instance.remove(); chart.current = null; candleSeries.current = null; volumeSeries.current = null; lines.current = {}; };
  }, []);
  useEffect(() => {
    const instance = chart.current;
    if (!instance || !candleSeries.current || !volumeSeries.current) return;
    try {
      const retainedViewport = !followRef.current && prior.current.symbol === symbol && prior.current.range === range ? instance.timeScale().getVisibleRange() : null;
      const data = bars.map(b => ({ time: (b.open_ms / 1000) as UTCTimestamp, open: Number(b.open), high: Number(b.high), low: Number(b.low), close: Number(b.close) }));
      if (data.some((b, i) => ![b.open, b.high, b.low, b.close].every(Number.isFinite) || b.low > Math.min(b.open, b.close) || b.high < Math.max(b.open, b.close) || (i > 0 && b.time <= data[i - 1].time))) throw new Error("Recorded candle data failed validation. Evidence retained; chart unavailable.");
      const times = new Set(data.map(d => d.time));
      const missing = data.flatMap((d, i) => i > 0 && d.time - data[i - 1].time > 60 ? [{ time: (data[i - 1].time + 60) as UTCTimestamp }] : []);
      candleSeries.current.setData([...data, ...missing].sort((a, b) => a.time - b.time));
      volumeSeries.current.setData(bars.map(b => ({ time: (b.open_ms / 1000) as UTCTimestamp, value: Number(b.volume), color: Number(b.close) >= Number(b.open) ? "#26dfa055" : "#f5758155" })));
      const span = data.length ? Math.max(0.00000001, Math.max(...data.map(b => b.high)) - Math.min(...data.map(b => b.low))) : 1;
      const precision = Math.min(8, Math.max(2, Math.ceil(-Math.log10(span / 100))));
      candleSeries.current.applyOptions({ priceFormat: { type: "price", precision, minMove: 10 ** -precision } });
      for (const key of Object.keys(colors) as Key[]) {
        const points = indicators?.points.filter(p => times.has((p.open_ms / 1000) as UTCTimestamp)) ?? [];
        lines.current[key]?.setData(points.map(p => p[key] == null ? { time: (p.open_ms / 1000) as UTCTimestamp } : { time: (p.open_ms / 1000) as UTCTimestamp, value: Number(p[key]) }));
      }
      const changed = prior.current.symbol !== symbol || prior.current.range !== range;
      if (data.length && (changed || followRef.current && prior.current.last !== data.at(-1)!.time)) {
        instance.timeScale().setVisibleRange({ from: (data.at(-1)!.time - (range - 1) * 60) as UTCTimestamp, to: (data.at(-1)!.time + 180) as UTCTimestamp });
      }
      prior.current = { symbol, range, last: data.at(-1)?.time ?? 0 };
      if (retainedViewport) instance.timeScale().setVisibleRange(retainedViewport);
      setError(null);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Recorded chart unavailable"); }
  }, [bars, indicators, range, symbol]);
  useEffect(() => { for (const key of Object.keys(colors) as Key[]) lines.current[key]?.applyOptions({ visible: enabled.includes(key) }); }, [enabled]);
  const candle = selected ?? bars.at(-1);
  const point = indicators?.points.find(p => p.open_ms === candle?.open_ms);
  const toggle = (keys: Key[]) => setEnabled(old => keys.every(k => old.includes(k)) ? old.filter(k => !keys.includes(k)) : [...new Set([...old, ...keys])]);
  const zoom = (factor: number) => { const scale = chart.current?.timeScale(); const window = scale?.getVisibleLogicalRange(); if (window) { const center = (window.from + window.to) / 2; const half = (window.to - window.from) * factor / 2; scale!.setVisibleLogicalRange({ from: center - half, to: center + half }); setFollow(false); } };
  return <div className="market-chart">
    <div className="chart-indicator-controls" role="group" aria-label="Chart indicators">
      {([[["ema"], "EMA 20"], [["sma"], "SMA 20"], [["vwap"], "VWAP window"], [["bb_upper", "bb_lower"], "Bollinger 20 / 2σ"]] as [Key[], string][]).map(([keys, label]) => <button key={label} aria-pressed={keys.every(k => enabled.includes(k))} onClick={() => toggle(keys)}>{label}</button>)}
      <button onClick={() => zoom(.7)} aria-label="Zoom in chart">+</button><button onClick={() => zoom(1.4)} aria-label="Zoom out chart">−</button>
      <button onClick={() => { chart.current?.timeScale().fitContent(); setFollow(false); }}>Fit history</button>
      <button aria-pressed={follow} onClick={() => { setFollow(!follow); if (!follow) chart.current?.timeScale().scrollToRealTime(); }}>Follow latest</button>
    </div>
    <div className="candle-readout" aria-live="off">{candle ? <><span>{localTime(candle.open_ms)} MT</span><span>O {value(candle.open)}</span><span>H {value(candle.high)}</span><span>L {value(candle.low)}</span><span>C {value(candle.close)}</span><span>Vol {value(candle.volume)}</span></> : "Awaiting recorded closed candles"}</div>
    {error && <p role="alert">{error}</p>}
    <div ref={host} role="img" aria-label={`Interactive ${symbol} closed one-minute candles and volume`} onPointerDown={() => setFollow(false)} onWheel={() => setFollow(false)} />
    <p className="indicator-readout">{enabled.map(k => `${k.replace("bb_", "band ").toUpperCase()} ${value(point?.[k])}`).join(" · ")}{enabled.length > 0 && <br />}
      {stale ? "Latest closed candle is stale. " : "Closed one-minute candles. "}Drag to pan, scroll or pinch to zoom; drag the price scale to adjust it. Times are Mountain time. Gaps remain empty.
      {enabled.includes("vwap") && ` VWAP uses typical price × recorded volume from ${indicators?.vwap_anchor_ms == null ? "an unavailable anchor" : localTime(indicators.vwap_anchor_ms) + " MT"}; it is not a complete-session or trade-level VWAP.`}
      {!!enabled.length && " Indicators warm up again after gaps. Chart controls do not change frozen strategy rules."}
    </p>
    <p className="chart-attribution"><a href="https://www.tradingview.com/" target="_blank" rel="noreferrer">TradingView Lightweight Charts™</a> · Copyright © 2025 TradingView, Inc. · Local Q-Trades observations</p>
  </div>;
});
