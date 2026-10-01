import { memo, useEffect, useRef } from 'react'
import uPlot from 'uplot'
import 'uplot/dist/uPlot.min.css'
import type { Sample, TraceMeta } from './debugStore'

const colors = ['#8ce0ae', '#f0bf78', '#79bbef', '#f18eb4', '#bb9bed']
export const TracePlot = memo(function TracePlot({ samples, meta, zoomKey }: { samples: Sample[]; meta: TraceMeta; zoomKey: number }) {
  const host = useRef<HTMLDivElement>(null)
  const plot = useRef<uPlot | null>(null)
  useEffect(() => {
    if (!host.current || !meta.signals.length) return
    const bools = meta.signals.filter(s => s.type === 'BOOL')
    const series: uPlot.Series[] = [{ label: 'Time (ms)' }, ...meta.signals.map((signal, i) => ({ label: signal.variable_id, stroke: colors[i % colors.length], width: 1.5, points: { show: false }, paths: signal.type === 'BOOL' ? uPlot.paths.stepped!({ align: 1 }) : undefined, scale: signal.type === 'BOOL' ? 'digital' : signal.type, value: (_: uPlot, v: number | null) => signal.type === 'BOOL' ? (v === null ? '—' : String(v - bools.findIndex(s => s.variable_id === signal.variable_id) * 2 === 1)) : String(v ?? '—') }))]
    const scales: uPlot.Scales = { x: { time: false }, digital: { range: [-0.15, Math.max(1, bools.length * 2 - 1) + .15] } }
    for (const signal of meta.signals) if (signal.type !== 'BOOL') scales[signal.type] = { auto: true }
    const analogTypes = [...new Set(meta.signals.filter(s => s.type !== 'BOOL').map(s => s.type))]
    plot.current = new uPlot({ width: Math.max(host.current.clientWidth - 24, 300), height: 180, series, scales, axes: [{ stroke: '#90a5a4', grid: { stroke: '#29363a' } }, { scale: bools.length ? 'digital' : analogTypes[0], stroke: '#90a5a4', grid: { stroke: '#29363a' }, values: (_, ticks) => ticks.map(v => bools.length ? Number.isInteger(v) ? v % 2 ? 'TRUE' : 'FALSE' : '' : String(v)) }, ...analogTypes.map(scale => ({ scale, side: 1, label: scale === 'TIME' ? 'TIME (ms)' : scale, stroke: '#90a5a4', grid: { show: false } }))], cursor: { drag: { x: true, y: false } } }, [[], ...meta.signals.map(() => [])], host.current)
    const observer = new ResizeObserver(() => plot.current?.setSize({ width: Math.max((host.current?.clientWidth || 324) - 24, 300), height: 180 }))
    observer.observe(host.current)
    return () => { observer.disconnect(); plot.current?.destroy(); plot.current = null }
  }, [meta.session_id, JSON.stringify(meta.signals)])
  useEffect(() => {
    const bools = meta.signals.filter(s => s.type === 'BOOL')
    plot.current?.setData([samples.map(s => s.t_ms), ...meta.signals.map(signal => samples.map(s => { const v = s.values[signal.variable_id]; return typeof v === 'boolean' ? Number(v) + bools.findIndex(b => b.variable_id === signal.variable_id) * 2 : typeof v === 'number' ? v : null }))], meta.state === 'recording')
  }, [samples, meta.signals, meta.state])
  useEffect(() => { if (samples.length) plot.current?.setScale('x', { min: samples[0].t_ms, max: samples.at(-1)!.t_ms || 1 }) }, [zoomKey])
  return <div className="trace-plot" ref={host} aria-label="Trace waveform: drag to zoom, move cursor to inspect" />
})
