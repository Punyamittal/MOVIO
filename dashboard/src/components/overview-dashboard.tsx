'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { RefreshCw } from 'lucide-react';
import { AppShell } from '@/components/app-shell';
import { DEFAULT_TTS_SERVER, fetchOverview, type OverviewResponse } from '@/lib/api';
import { cn } from '@/lib/utils';

function fmt(n: number | null | undefined, digits = 0): string {
  if (n == null || Number.isNaN(n)) return '—';
  return n.toLocaleString(undefined, {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits > 0 ? Math.min(digits, 2) : 0,
  });
}

function shortDay(iso: string): string {
  const d = new Date(`${iso}T12:00:00Z`);
  return d.toLocaleDateString(undefined, { weekday: 'short' });
}

function langLabel(code: string): string {
  const c = code.toLowerCase();
  if (c === 'ta' || c === 'tamil') return 'Tamil';
  if (c === 'en' || c === 'english') return 'English';
  if (c === 'tanglish') return 'Tanglish';
  if (c === 'auto') return 'Auto';
  return code || 'Unknown';
}

function timeLabel(ts?: string): string {
  if (!ts) return '';
  try {
    return new Date(ts).toLocaleTimeString(undefined, {
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return '';
  }
}

function BarList({
  items,
  valueKey = 'value',
}: {
  items: { label: string; value: number; color?: string }[];
  valueKey?: string;
}) {
  const max = Math.max(1, ...items.map((i) => i.value));
  return (
    <div className="space-y-2.5">
      {items.length === 0 ? (
        <p className="text-sm text-[#94a3b0]">No data yet — generate speech in Studio.</p>
      ) : (
        items.map((item) => (
          <div key={`${item.label}-${valueKey}`}>
            <div className="mb-1 flex items-baseline justify-between gap-2 text-sm">
              <span className="font-medium capitalize">{item.label}</span>
              <span className="tabular-nums text-[#5a6a7a]">{item.value}</span>
            </div>
            <div className="h-2 overflow-hidden rounded-sm bg-[#e8eef2]">
              <div
                className="h-full rounded-sm bg-[#0f6e6e]"
                style={{
                  width: `${(item.value / max) * 100}%`,
                  background: item.color || '#0f6e6e',
                }}
              />
            </div>
          </div>
        ))
      )}
    </div>
  );
}

function ActivityBars({ data }: { data: { day: string; count: number }[] }) {
  const max = Math.max(1, ...data.map((d) => d.count));
  return (
    <div className="flex h-40 items-end gap-2">
      {data.map((d) => (
        <div key={d.day} className="flex flex-1 flex-col items-center gap-2">
          <div className="flex h-28 w-full items-end justify-center">
            <div
              className="w-full max-w-[2rem] rounded-sm bg-[#0a1628]"
              style={{ height: `${Math.max(4, (d.count / max) * 100)}%` }}
              title={`${d.count}`}
            />
          </div>
          <span className="text-[11px] font-medium text-[#5a6a7a]">{shortDay(d.day)}</span>
        </div>
      ))}
    </div>
  );
}

function Heatmap({
  data,
}: {
  data: Record<string, Record<string, number>>;
}) {
  const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  const hours = Array.from({ length: 24 }, (_, i) => i);
  let max = 1;
  for (const day of days) {
    for (const h of hours) {
      max = Math.max(max, data[day]?.[String(h)] || 0);
    }
  }
  return (
    <div className="overflow-x-auto">
      <div className="min-w-[520px]">
        <div className="mb-1 grid grid-cols-[2.5rem_repeat(24,minmax(0,1fr))] gap-0.5 text-[9px] text-[#94a3b0]">
          <span />
          {hours.filter((h) => h % 3 === 0).map((h) => (
            <span key={h} className="col-span-3 text-center">
              {h}
            </span>
          ))}
        </div>
        {days.map((day) => (
          <div
            key={day}
            className="mb-0.5 grid grid-cols-[2.5rem_repeat(24,minmax(0,1fr))] gap-0.5"
          >
            <span className="text-[10px] font-medium text-[#5a6a7a]">{day}</span>
            {hours.map((h) => {
              const v = data[day]?.[String(h)] || 0;
              const t = v / max;
              return (
                <div
                  key={`${day}-${h}`}
                  title={`${day} ${h}:00 · ${v}`}
                  className="aspect-square rounded-[2px]"
                  style={{
                    background:
                      v === 0
                        ? '#e8eef2'
                        : `rgba(15, 110, 110, ${0.18 + t * 0.82})`,
                  }}
                />
              );
            })}
          </div>
        ))}
        <div className="mt-2 flex items-center gap-2 text-[10px] text-[#94a3b0]">
          <span>Less</span>
          <div className="flex gap-0.5">
            {[0, 0.25, 0.5, 0.75, 1].map((t) => (
              <div
                key={t}
                className="h-2.5 w-2.5 rounded-[2px]"
                style={{
                  background: t === 0 ? '#e8eef2' : `rgba(15, 110, 110, ${0.18 + t * 0.82})`,
                }}
              />
            ))}
          </div>
          <span>More</span>
        </div>
      </div>
    </div>
  );
}

export default function OverviewDashboard() {
  const [server] = useState(DEFAULT_TTS_SERVER);
  const [data, setData] = useState<OverviewResponse | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [trendMode, setTrendMode] = useState<'voice' | 'lang'>('voice');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const overview = await fetchOverview(server);
      setData(overview);
    } catch (e) {
      setError(String(e));
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [server]);

  useEffect(() => {
    void load();
    const id = window.setInterval(() => void load(), 30_000);
    return () => window.clearInterval(id);
  }, [load]);

  const langItems = useMemo(() => {
    const mix = data?.charts.language_mix || {};
    return Object.entries(mix)
      .map(([label, value]) => ({ label: langLabel(label), value }))
      .sort((a, b) => b.value - a.value);
  }, [data]);

  const voiceItems = useMemo(() => {
    const mix = data?.charts.voice_usage || {};
    return Object.entries(mix)
      .map(([label, value]) => ({ label, value }))
      .sort((a, b) => b.value - a.value);
  }, [data]);

  const ttfaDist = useMemo(() => {
    const d = data?.charts.ttfa_distribution || {};
    const order = ['0-200', '200-400', '400-600', '600-800', '800-1000', '1000+'];
    return order.map((label) => ({ label: `${label}ms`, value: d[label] || 0 }));
  }, [data]);

  const funnel = data?.charts.funnel;
  const studio = funnel?.studio || 0;
  const batch = funnel?.batch || 0;
  const comparison = funnel?.comparison || 0;
  const evaluation = funnel?.evaluation || 0;

  const kpis = data?.kpis;
  const p99 = kpis?.p99_latency_ms;
  const target = kpis?.ttfa_target_ms ?? 500;

  return (
    <AppShell
      online={Boolean(data?.status.engine_online)}
      statusLabel={data?.status.label || (error ? 'Engine offline' : 'Connecting…')}
      statusDetail={data?.status.detail || error || 'Loading TTS runtime…'}
      version={data?.version || 'v1.1 prototype'}
    >
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-[family-name:var(--font-display)] text-3xl font-extrabold tracking-tight">
            Welcome to Movio
          </h1>
          <p className="mt-2 max-w-2xl text-sm leading-relaxed text-[#5a6a7a]">
            Low-latency Tamil, English and Tanglish Text-to-Speech for transportation voice
            agents. Self-hosted, context-aware, sub-500ms p99 target.
          </p>
          <div className="mt-4 flex flex-wrap gap-2">
            <Link
              href="/studio"
              className="inline-flex h-10 items-center bg-[#0a1628] px-4 text-sm font-semibold text-white transition hover:bg-[#0f6e6e]"
            >
              Open Studio
            </Link>
            <Link
              href="/phones"
              className="inline-flex h-10 items-center border border-[#cfd8e0] bg-white px-4 text-sm font-semibold text-[#0a1628] transition hover:border-[#0f6e6e]"
            >
              Two-Phone Test
            </Link>
            <Link
              href="/agent"
              className="inline-flex h-10 items-center border border-[#cfd8e0] bg-white px-4 text-sm font-semibold text-[#0a1628] transition hover:border-[#0f6e6e]"
            >
              Live Agent
            </Link>
          </div>
        </div>
        <button
          type="button"
          onClick={() => void load()}
          className="inline-flex h-10 items-center gap-2 border border-[#cfd8e0] bg-white px-3 text-sm font-medium text-[#0a1628] transition hover:border-[#0f6e6e]"
        >
          <RefreshCw className={cn('h-3.5 w-3.5', loading && 'animate-spin')} />
          Refresh
        </button>
      </div>

      <p className="mb-4 text-sm text-[#5a6a7a]">
        <span className="font-semibold text-[#0a1628]">Dashboard</span>
        <span className="mx-2 text-[#cfd8e0]">·</span>
        Live KPIs across synthesis, benchmark and evaluation. Auto-refreshes every 30 seconds.
      </p>

      {error && (
        <div className="mb-4 border border-[#f0c2bd] bg-[#fff5f4] px-4 py-3 text-sm text-[#b42318]">
          Could not reach TTS API at {server}. Start movio-indicvoice on :8001. {error}
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {[
          {
            label: 'Syntheses',
            value: fmt(kpis?.syntheses),
            sub: `${fmt(kpis?.syntheses_24h)} in last 24h`,
          },
          {
            label: 'Avg TTFA',
            value: fmt(kpis?.avg_ttfa_ms, 0),
            unit: 'ms',
            sub: `min ${fmt(kpis?.min_ttfa_ms)} · max ${fmt(kpis?.max_ttfa_ms)}`,
          },
          {
            label: 'Audio minutes',
            value: fmt(kpis?.audio_minutes, 2),
            unit: 'min',
            sub: 'Total generated',
          },
          {
            label: 'p99 latency',
            value: fmt(p99, 0),
            unit: 'ms',
            sub: `Target ≤ ${target}ms`,
            warn: p99 != null && p99 > target,
          },
        ].map((card) => (
          <div key={card.label} className="border border-[#cfd8e0] bg-white px-4 py-4">
            <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#5a6a7a]">
              {card.label}
            </p>
            <p className="mt-2 font-[family-name:var(--font-display)] text-3xl font-bold tabular-nums">
              {card.value}
              {card.unit ? (
                <span className="ml-1 text-sm font-medium text-[#94a3b0]">{card.unit}</span>
              ) : null}
            </p>
            <p className={cn('mt-1 text-xs', card.warn ? 'text-[#b42318]' : 'text-[#5a6a7a]')}>
              {card.sub}
            </p>
          </div>
        ))}
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <section className="border border-[#cfd8e0] bg-white p-4 xl:col-span-1">
          <h2 className="text-sm font-semibold">Activity (last 7 days)</h2>
          <div className="mt-4">
            <ActivityBars data={data?.charts.activity_7d || []} />
          </div>
        </section>
        <section className="border border-[#cfd8e0] bg-white p-4">
          <h2 className="text-sm font-semibold">Language mix</h2>
          <div className="mt-4">
            <BarList items={langItems} />
          </div>
        </section>
        <section className="border border-[#cfd8e0] bg-white p-4">
          <h2 className="text-sm font-semibold">Voice usage</h2>
          <div className="mt-4">
            <BarList items={voiceItems} />
          </div>
        </section>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <section className="border border-[#cfd8e0] bg-white p-4">
          <h2 className="text-sm font-semibold">Time-to-first-audio distribution</h2>
          <div className="mt-4">
            <BarList items={ttfaDist} />
          </div>
          <div className="mt-4 flex flex-wrap gap-3 text-[11px] text-[#5a6a7a]">
            <span>≤ {target}ms (target)</span>
            <span>500–800ms</span>
            <span>&gt; 800ms</span>
          </div>
        </section>

        <section className="border border-[#cfd8e0] bg-white p-4">
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-sm font-semibold">Synthesis trend · last 7 days</h2>
            <div className="flex gap-1 text-xs">
              <button
                type="button"
                onClick={() => setTrendMode('voice')}
                className={cn(
                  'px-2 py-1',
                  trendMode === 'voice' ? 'bg-[#0a1628] text-white' : 'bg-[#e8eef2] text-[#5a6a7a]'
                )}
              >
                By voice
              </button>
              <button
                type="button"
                onClick={() => setTrendMode('lang')}
                className={cn(
                  'px-2 py-1',
                  trendMode === 'lang' ? 'bg-[#0a1628] text-white' : 'bg-[#e8eef2] text-[#5a6a7a]'
                )}
              >
                By language
              </button>
            </div>
          </div>
          <div className="mt-4 space-y-3">
            {(trendMode === 'voice' ? data?.charts.trend_by_voice : data?.charts.trend_by_lang)?.map(
              (row) => {
                const parts =
                  trendMode === 'voice'
                    ? Object.entries((row as { voices: Record<string, number> }).voices || {})
                    : Object.entries((row as { langs: Record<string, number> }).langs || {});
                const total = parts.reduce((s, [, v]) => s + v, 0);
                return (
                  <div key={row.day}>
                    <div className="mb-1 flex justify-between text-[11px] text-[#5a6a7a]">
                      <span>{shortDay(row.day)}</span>
                      <span>{total}</span>
                    </div>
                    <div className="flex h-3 overflow-hidden rounded-sm bg-[#e8eef2]">
                      {parts.map(([k, v], idx) => (
                        <div
                          key={k}
                          style={{
                            width: `${total ? (v / total) * 100 : 0}%`,
                            background: ['#0f6e6e', '#0a1628', '#5a6a7a', '#94a3b0'][idx % 4],
                          }}
                          title={`${k}: ${v}`}
                        />
                      ))}
                    </div>
                  </div>
                );
              }
            )}
          </div>
        </section>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <section className="border border-[#cfd8e0] bg-white p-4">
          <h2 className="text-sm font-semibold">Weekly activity heatmap · day × hour</h2>
          <div className="mt-4">
            <Heatmap data={data?.charts.heatmap || {}} />
          </div>
        </section>

        <section className="border border-[#cfd8e0] bg-white p-4">
          <h2 className="text-sm font-semibold">Synthesis funnel · Studio → Batch → Comparison → Evaluation</h2>
          <div className="mt-5 grid grid-cols-4 gap-2 text-center">
            {[
              { label: 'Studio', value: studio, pct: null as string | null },
              {
                label: 'Batch',
                value: batch,
                pct: studio ? `${Math.round((batch / studio) * 100)}% of Studio` : null,
              },
              {
                label: 'Comparison',
                value: comparison,
                pct: studio ? `${Math.round((comparison / studio) * 100)}% of Studio` : null,
              },
              {
                label: 'Evaluation',
                value: evaluation,
                pct: studio ? `${Math.round((evaluation / studio) * 100)}% of Studio` : null,
              },
            ].map((step) => (
              <div key={step.label} className="border border-[#e8eef2] bg-[#f7f9fb] px-2 py-3">
                <p className="font-[family-name:var(--font-display)] text-2xl font-bold tabular-nums">
                  {step.value}
                </p>
                <p className="mt-1 text-xs font-semibold">{step.label}</p>
                {step.pct ? <p className="mt-1 text-[10px] text-[#5a6a7a]">{step.pct}</p> : null}
              </div>
            ))}
          </div>
        </section>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <section className="border border-[#cfd8e0] bg-white p-4 xl:col-span-1">
          <h2 className="text-sm font-semibold">Quick actions</h2>
          <div className="mt-3 space-y-2">
            {(data?.quick_actions || []).map((a) => (
              <Link
                key={a.id}
                href={a.href}
                className="block border border-[#e8eef2] px-3 py-3 transition hover:border-[#0f6e6e]"
              >
                <p className="text-sm font-semibold">{a.title}</p>
                <p className="mt-1 text-xs text-[#5a6a7a]">{a.body}</p>
              </Link>
            ))}
          </div>
        </section>

        <section className="border border-[#cfd8e0] bg-white p-4 xl:col-span-2">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold">Recent syntheses</h2>
            <Link href="/studio" className="text-xs font-semibold text-[#0f6e6e]">
              View all
            </Link>
          </div>
          <ul className="mt-3 divide-y divide-[#e8eef2]">
            {(data?.recent || []).length === 0 ? (
              <li className="py-6 text-sm text-[#94a3b0]">
                No live syntheses yet. Open Studio and generate speech — KPIs update automatically.
              </li>
            ) : (
              data?.recent.map((row, idx) => (
                <li key={`${row.ts}-${idx}`} className="flex flex-wrap items-start justify-between gap-3 py-3">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm leading-snug text-[#0a1628]">{row.text || '(empty)'}</p>
                    <p className="mt-1 text-[11px] text-[#5a6a7a]">
                      <span className="capitalize">{langLabel(row.lang)}</span>
                      <span className="mx-1">·</span>
                      <span className="capitalize">{row.voice || row.backend}</span>
                      <span className="mx-1">·</span>
                      TTFA {fmt(row.ttfa_ms)}ms
                    </p>
                  </div>
                  <span className="shrink-0 text-[11px] tabular-nums text-[#94a3b0]">
                    {timeLabel(row.ts)}
                  </span>
                </li>
              ))
            )}
          </ul>
        </section>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <div className="border border-[#cfd8e0] bg-white px-4 py-4">
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#5a6a7a]">
            Avg MOS
          </p>
          <p className="mt-2 font-[family-name:var(--font-display)] text-3xl font-bold">
            {fmt(data?.evaluation.avg_mos, 2)}
          </p>
          <p className="mt-1 text-xs text-[#5a6a7a]">
            {data?.evaluation.mos_evaluations || 0} evaluations
          </p>
        </div>
        <div className="border border-[#cfd8e0] bg-white px-4 py-4">
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#5a6a7a]">
            Best p99
          </p>
          <p className="mt-2 font-[family-name:var(--font-display)] text-3xl font-bold">
            {fmt(data?.benchmark.best_p99_ttfa_ms, 0)}
            {data?.benchmark.best_p99_ttfa_ms != null ? (
              <span className="ml-1 text-sm font-medium text-[#94a3b0]">ms</span>
            ) : null}
          </p>
          <p className="mt-1 text-xs text-[#5a6a7a]">
            {data?.benchmark.has_runs
              ? data.benchmark.best_backend || 'from benchmark runs'
              : '0 benchmark runs'}
          </p>
        </div>
        <div className="border border-[#cfd8e0] bg-white px-4 py-4">
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#5a6a7a]">
            Latest run
          </p>
          <p className="mt-2 font-[family-name:var(--font-display)] text-xl font-bold">
            {data?.benchmark.phone_avg_e2e_round2_ms != null
              ? `${fmt(data.benchmark.phone_avg_e2e_round2_ms, 0)} ms`
              : '—'}
          </p>
          <p className="mt-1 text-xs text-[#5a6a7a]">
            {data?.benchmark.phone_avg_e2e_round2_ms != null
              ? 'Phone cache sim round-2 e2e'
              : 'No runs yet'}
          </p>
        </div>
        <div className="border border-[#cfd8e0] bg-white px-4 py-4">
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#5a6a7a]">
            Avg WER
          </p>
          <p className="mt-2 font-[family-name:var(--font-display)] text-3xl font-bold">
            {data?.evaluation.avg_wer != null ? `${fmt(data.evaluation.avg_wer, 1)}%` : '—'}
          </p>
          <p className="mt-1 text-xs text-[#5a6a7a]">
            {data?.evaluation.acceptance_pass != null && data?.evaluation.acceptance_total != null
              ? `Acceptance ${data.evaluation.acceptance_pass}/${data.evaluation.acceptance_total}`
              : 'Word error rate'}
          </p>
        </div>
      </div>

      <footer className="mt-8 border-t border-[#cfd8e0] pt-4 text-xs text-[#5a6a7a]">
        Movio · Low-Latency Tamil/English/Tanglish TTS · p99 ≤ {target} ms target · 15–20 concurrent ·
        Self-hosted
      </footer>
    </AppShell>
  );
}
