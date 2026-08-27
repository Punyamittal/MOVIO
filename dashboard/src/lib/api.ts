export const DEFAULT_TTS_SERVER =
  process.env.NEXT_PUBLIC_TTS_SERVER?.replace(/\/$/, '') || 'http://127.0.0.1:8001';

export type OverviewResponse = {
  ok: boolean;
  version: string;
  status: {
    engine_online: boolean;
    label: string;
    detail: string;
    default_backend?: string;
    loaded_backends?: string[];
    device?: string;
  };
  kpis: {
    syntheses: number;
    syntheses_24h: number;
    avg_ttfa_ms: number | null;
    min_ttfa_ms: number | null;
    max_ttfa_ms: number | null;
    audio_minutes: number;
    p99_latency_ms: number | null;
    ttfa_target_ms: number;
    aspirational_ttfa_ms?: number;
  };
  charts: {
    activity_7d: { day: string; count: number }[];
    language_mix: Record<string, number>;
    voice_usage: Record<string, number>;
    ttfa_distribution: Record<string, number>;
    trend_by_voice: { day: string; voices: Record<string, number> }[];
    trend_by_lang: { day: string; langs: Record<string, number> }[];
    heatmap: Record<string, Record<string, number>>;
    funnel: { studio: number; batch: number; comparison: number; evaluation: number };
  };
  recent: {
    text: string;
    lang: string;
    voice: string;
    backend: string;
    ttfa_ms: number | null;
    ts?: string;
  }[];
  benchmark: {
    has_runs: boolean;
    best_p99_ttfa_ms: number | null;
    best_backend: string | null;
    phone_avg_e2e_round1_ms?: number | null;
    phone_avg_e2e_round2_ms?: number | null;
    comparison?: Record<
      string,
      { ttfa_ms?: { p50?: number; p99?: number; mean?: number; n?: number } }
    >;
  };
  evaluation: {
    acceptance_summary: string | null;
    acceptance_pass: number | null;
    acceptance_total: number | null;
    avg_wer: number | null;
    avg_mos: number | null;
    mos_evaluations: number;
    wer_n?: number | null;
  };
  voices: { id: string; label: string }[];
  quick_actions: { id: string; title: string; body: string; href: string }[];
};

export async function fetchOverview(server = DEFAULT_TTS_SERVER): Promise<OverviewResponse> {
  const res = await fetch(`${server.replace(/\/$/, '')}/dashboard/overview`, {
    cache: 'no-store',
  });
  if (!res.ok) {
    throw new Error(`Overview API ${res.status}`);
  }
  return res.json() as Promise<OverviewResponse>;
}
