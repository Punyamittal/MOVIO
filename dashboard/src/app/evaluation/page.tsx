'use client';

import { useEffect, useState } from 'react';
import { ShellFrame } from '@/components/section-frame';
import { DEFAULT_TTS_SERVER, fetchOverview, type OverviewResponse } from '@/lib/api';

export default function EvaluationPage() {
  const [data, setData] = useState<OverviewResponse | null>(null);

  useEffect(() => {
    void fetchOverview(DEFAULT_TTS_SERVER)
      .then(setData)
      .catch(() => setData(null));
  }, []);

  const e = data?.evaluation;

  return (
    <ShellFrame
      title="Evaluation"
      subtitle="Quality metrics from acceptance tests, WER/CER, and MOS scoring artifacts."
    >
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="border border-[#cfd8e0] bg-white px-4 py-4">
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#5a6a7a]">
            Acceptance
          </p>
          <p className="mt-2 text-3xl font-bold tabular-nums">
            {e?.acceptance_pass != null && e?.acceptance_total != null
              ? `${e.acceptance_pass}/${e.acceptance_total}`
              : '—'}
          </p>
          <p className="mt-1 text-xs text-[#5a6a7a]">{e?.acceptance_summary || 'No results'}</p>
        </div>
        <div className="border border-[#cfd8e0] bg-white px-4 py-4">
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#5a6a7a]">
            Avg WER
          </p>
          <p className="mt-2 text-3xl font-bold tabular-nums">
            {e?.avg_wer != null ? `${e.avg_wer}%` : '—'}
          </p>
          <p className="mt-1 text-xs text-[#5a6a7a]">
            {e?.wer_n ? `${e.wer_n} sentences` : 'WER artifact empty or unavailable'}
          </p>
        </div>
        <div className="border border-[#cfd8e0] bg-white px-4 py-4">
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#5a6a7a]">
            Avg MOS
          </p>
          <p className="mt-2 text-3xl font-bold tabular-nums">{e?.avg_mos ?? '—'}</p>
          <p className="mt-1 text-xs text-[#5a6a7a]">{e?.mos_evaluations || 0} scored rows</p>
        </div>
      </div>
    </ShellFrame>
  );
}
