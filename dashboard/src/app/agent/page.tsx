'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { ShellFrame } from '@/components/section-frame';
import { DEFAULT_TTS_SERVER, fetchOverview } from '@/lib/api';
import {
  FALLBACK_VOICES,
  fetchVoices,
  synthesizeSpeech,
  type StudioVoice,
} from '@/lib/studio';
import { cn } from '@/lib/utils';

type FlowTurn = { role: string; text: string };
type AgentFlow = { id: string; title: string; turns: FlowTurn[] };

type ChatTurn = FlowTurn & {
  audioUrl?: string;
  ttfaMs?: number | null;
  playing?: boolean;
};

export default function AgentPage() {
  const [flows, setFlows] = useState<AgentFlow[]>([]);
  const [flowId, setFlowId] = useState('');
  const [active, setActive] = useState(false);
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [voices, setVoices] = useState<StudioVoice[]>(FALLBACK_VOICES);
  const [voiceId, setVoiceId] = useState('jaya');
  const [busyIdx, setBusyIdx] = useState<number | null>(null);
  const [error, setError] = useState('');
  const [online, setOnline] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const urls = useRef<string[]>([]);

  useEffect(() => {
    void fetchVoices(DEFAULT_TTS_SERVER).then(setVoices);
    void fetchOverview(DEFAULT_TTS_SERVER)
      .then((o) => setOnline(Boolean(o.status.engine_online)))
      .catch(() => setOnline(false));
    void (async () => {
      try {
        const res = await fetch(`${DEFAULT_TTS_SERVER}/studio/agent/flows`, {
          cache: 'no-store',
        });
        if (!res.ok) throw new Error(`Flows unavailable (${res.status})`);
        const data = await res.json();
        const list = (data.flows as AgentFlow[]) || [];
        setFlows(list);
        if (list[0]) setFlowId(list[0].id);
      } catch (e) {
        setError(String(e instanceof Error ? e.message : e));
      }
    })();
    return () => {
      urls.current.forEach((u) => URL.revokeObjectURL(u));
      audioRef.current?.pause();
    };
  }, []);

  const voiceStyle =
    voices.find((v) => v.id === voiceId)?.style || FALLBACK_VOICES[0].style;

  const startCall = () => {
    const flow = flows.find((f) => f.id === flowId);
    if (!flow) return;
    setActive(true);
    setTurns(flow.turns.map((t) => ({ ...t })));
    setError('');
  };

  const speakAgent = async (index: number) => {
    const turn = turns[index];
    if (!turn || turn.role !== 'agent') return;
    setBusyIdx(index);
    setError('');
    try {
      const result = await synthesizeSpeech({
        text: turn.text,
        voiceStyle,
        targetLang: 'en',
        backend: 'edge_fast',
        server: DEFAULT_TTS_SERVER,
        sourceHint: 'agent',
      });
      urls.current.push(result.audioUrl);
      setTurns((prev) =>
        prev.map((t, i) =>
          i === index
            ? { ...t, audioUrl: result.audioUrl, ttfaMs: result.ttfaMs }
            : t
        )
      );
      if (audioRef.current) {
        audioRef.current.src = result.audioUrl;
        void audioRef.current.play().catch(() => undefined);
      }
      setOnline(true);
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setBusyIdx(null);
    }
  };

  const stats = useMemo(() => {
    const spoken = turns.filter((t) => t.role === 'agent' && t.ttfaMs != null);
    const avg =
      spoken.length === 0
        ? null
        : spoken.reduce((s, t) => s + (t.ttfaMs || 0), 0) / spoken.length;
    return {
      activeTurns: active ? turns.length : 0,
      avgTtfa: avg,
      synthCount: spoken.length,
    };
  }, [turns, active]);

  return (
    <ShellFrame
      title="Live Voice Agent"
      subtitle="Multi-turn taxi contact-center flows — click an agent bubble to synthesize and play speech."
    >
      <audio ref={audioRef} className="hidden" />

      <div className="mb-4 grid gap-3 sm:grid-cols-3">
        <div className="border border-[#cfd8e0] bg-white px-4 py-3">
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#5a6a7a]">
            Service
          </p>
          <p className="mt-1 text-sm font-semibold">
            <span
              className={cn(
                'mr-2 inline-block h-2 w-2 rounded-full',
                online ? 'bg-[#0f6e6e]' : 'bg-[#b42318]'
              )}
            />
            {online ? 'Service online' : 'Service offline'}
          </p>
        </div>
        <div className="border border-[#cfd8e0] bg-white px-4 py-3">
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#5a6a7a]">
            Active turns
          </p>
          <p className="mt-1 font-[family-name:var(--font-display)] text-2xl font-bold tabular-nums">
            {stats.activeTurns}
          </p>
        </div>
        <div className="border border-[#cfd8e0] bg-white px-4 py-3">
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#5a6a7a]">
            Avg TTFA
          </p>
          <p className="mt-1 font-[family-name:var(--font-display)] text-2xl font-bold tabular-nums">
            {stats.avgTtfa == null ? '—' : `${Math.round(stats.avgTtfa)}`}
            {stats.avgTtfa != null ? (
              <span className="ml-1 text-sm font-medium text-[#94a3b0]">ms</span>
            ) : null}
          </p>
        </div>
      </div>

      <div className="mb-4 flex flex-wrap items-end gap-3 border border-[#cfd8e0] bg-white p-4">
        <div className="min-w-[14rem] flex-1">
          <label className="mb-2 block text-[11px] font-semibold uppercase tracking-[0.14em] text-[#5a6a7a]">
            Scenario flow
          </label>
          <select
            value={flowId}
            onChange={(e) => setFlowId(e.target.value)}
            className="w-full border border-[#cfd8e0] bg-white px-3 py-2.5 text-sm outline-none focus:border-[#0f6e6e]"
          >
            {flows.map((f) => (
              <option key={f.id} value={f.id}>
                {f.title}
              </option>
            ))}
          </select>
        </div>
        <div className="min-w-[12rem]">
          <label className="mb-2 block text-[11px] font-semibold uppercase tracking-[0.14em] text-[#5a6a7a]">
            Agent voice
          </label>
          <select
            value={voiceId}
            onChange={(e) => setVoiceId(e.target.value)}
            className="w-full border border-[#cfd8e0] bg-white px-3 py-2.5 text-sm outline-none focus:border-[#0f6e6e]"
          >
            {voices.map((v) => (
              <option key={v.id} value={v.id}>
                {v.label} — {v.tagline}
              </option>
            ))}
          </select>
        </div>
        <button
          type="button"
          onClick={startCall}
          disabled={!flowId}
          className="inline-flex h-10 items-center bg-[#0a1628] px-4 text-sm font-semibold text-white hover:bg-[#0f6e6e] disabled:opacity-60"
        >
          Start call
        </button>
      </div>

      {error ? (
        <p className="mb-3 border border-[#f0c2bd] bg-[#fff5f4] px-3 py-2 text-sm text-[#b42318]">
          {error}
        </p>
      ) : null}

      <div className="min-h-[20rem] border border-[#cfd8e0] bg-white p-4">
        {!active ? (
          <p className="text-sm text-[#94a3b0]">
            Choose a scenario and press Start call to load the multi-turn transcript.
          </p>
        ) : (
          <div className="space-y-3">
            {turns.map((t, i) => {
              const isAgent = t.role === 'agent';
              return (
                <button
                  key={`${t.role}-${i}`}
                  type="button"
                  disabled={!isAgent || busyIdx !== null}
                  onClick={() => (isAgent ? void speakAgent(i) : undefined)}
                  className={cn(
                    'max-w-[85%] rounded-md px-3.5 py-2.5 text-left text-sm leading-relaxed transition',
                    isAgent
                      ? 'ml-auto block bg-[#0a1628] text-white hover:bg-[#0f6e6e] disabled:opacity-70'
                      : 'block cursor-default bg-[#e8eef2] text-[#0a1628]'
                  )}
                >
                  <span className="mb-1 block text-[10px] font-semibold uppercase tracking-[0.14em] opacity-70">
                    {isAgent ? 'Agent' : 'Caller'}
                    {isAgent ? ' · click to speak' : ''}
                  </span>
                  {busyIdx === i ? (
                    <span className="inline-flex items-center gap-2">
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      Synthesizing…
                    </span>
                  ) : (
                    t.text
                  )}
                  {t.ttfaMs != null ? (
                    <span className="mt-1 block text-[10px] opacity-70">
                      TTFA {Math.round(t.ttfaMs)} ms
                    </span>
                  ) : null}
                </button>
              );
            })}
          </div>
        )}
      </div>

      <p className="mt-4 text-xs leading-relaxed text-[#5a6a7a]">
        <span className="font-semibold text-[#0a1628]">How it works · </span>
        Flows come from <code className="text-[#0f6e6e]">GET /studio/agent/flows</code>. Starting a
        call loads the scripted turns. Clicking an agent bubble calls{' '}
        <code className="text-[#0f6e6e]">POST /tts</code> (edge_fast) and autoplays the audio so
        you can demo contact-center replies without phones.
      </p>
    </ShellFrame>
  );
}
