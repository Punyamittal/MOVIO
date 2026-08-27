'use client';

import { useEffect, useState } from 'react';
import { ShellFrame } from '@/components/section-frame';
import { DEFAULT_TTS_SERVER, fetchOverview, type OverviewResponse } from '@/lib/api';

export default function BenchmarkPage() {
  const [data, setData] = useState<OverviewResponse | null>(null);

  useEffect(() => {
    void fetchOverview(DEFAULT_TTS_SERVER)
      .then(setData)
      .catch(() => setData(null));
  }, []);

  const b = data?.benchmark;
  const comparison = b?.comparison;

  return (
    <ShellFrame
      title="Benchmark"
      subtitle="Latency & cost snapshots from on-disk benchmark runs plus live p99."
    >
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="border border-[#cfd8e0] bg-white px-4 py-4">
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#5a6a7a]">
            Live p99
          </p>
          <p className="mt-2 text-3xl font-bold tabular-nums">
            {data?.kpis.p99_latency_ms ?? '—'}
            <span className="ml-1 text-sm font-medium text-[#94a3b0]">ms</span>
          </p>
        </div>
        <div className="border border-[#cfd8e0] bg-white px-4 py-4">
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#5a6a7a]">
            Best artifact p99
          </p>
          <p className="mt-2 text-3xl font-bold tabular-nums">
            {b?.best_p99_ttfa_ms ?? '—'}
            <span className="ml-1 text-sm font-medium text-[#94a3b0]">ms</span>
          </p>
          <p className="mt-1 text-xs text-[#5a6a7a]">{b?.best_backend || 'No runs'}</p>
        </div>
        <div className="border border-[#cfd8e0] bg-white px-4 py-4">
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#5a6a7a]">
            Phone e2e (cached)
          </p>
          <p className="mt-2 text-3xl font-bold tabular-nums">
            {b?.phone_avg_e2e_round2_ms ?? '—'}
            <span className="ml-1 text-sm font-medium text-[#94a3b0]">ms</span>
          </p>
        </div>
      </div>

      <div className="mt-4 border border-[#cfd8e0] bg-white p-4">
        <h2 className="text-sm font-semibold">Benchmark comparison (summary.json)</h2>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[420px] text-left text-sm">
            <thead className="text-[11px] uppercase tracking-[0.12em] text-[#5a6a7a]">
              <tr>
                <th className="py-2">Backend</th>
                <th>p50 TTFA</th>
                <th>mean</th>
                <th>p99</th>
              </tr>
            </thead>
            <tbody>
              {comparison && Object.keys(comparison).length > 0 ? (
                Object.entries(comparison).map(([name, block]) => (
                  <tr key={name} className="border-t border-[#e8eef2]">
                    <td className="py-2 font-medium">{name}</td>
                    <td>{block?.ttfa_ms?.p50 ?? '—'}</td>
                    <td>{block?.ttfa_ms?.mean ?? '—'}</td>
                    <td>{block?.ttfa_ms?.p99 ?? '—'}</td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={4} className="py-4 text-[#94a3b0]">
                    No benchmark summary loaded.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </ShellFrame>
  );
}
