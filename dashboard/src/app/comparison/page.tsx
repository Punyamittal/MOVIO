'use client';

import { useEffect, useRef, useState } from 'react';
import { ArrowLeftRight, Loader2 } from 'lucide-react';
import { ShellFrame } from '@/components/section-frame';
import { DEFAULT_TTS_SERVER } from '@/lib/api';
import {
  FALLBACK_VOICES,
  fetchVoices,
  synthesizeSpeech,
  type StudioVoice,
} from '@/lib/studio';
import { cn } from '@/lib/utils';

const LANGS = [
  { id: 'en', label: 'English' },
  { id: 'ta', label: 'தமிழ்' },
  { id: 'tanglish', label: 'Tanglish' },
] as const;

const SPEEDS = [0.5, 1.0, 2.0] as const;

type SideState = {
  voiceId: string;
  speed: number;
  audioUrl: string | null;
  ttfaMs: number | null;
  fullMs: number | null;
  error: string;
};

type SavedComparison = {
  ts: string;
  text: string;
  lang: string;
  side_a: Record<string, unknown>;
  side_b: Record<string, unknown>;
  winner?: string;
};

const labelClass =
  'mb-2 block text-[11px] font-semibold uppercase tracking-[0.14em] text-[#5a6a7a]';
const fieldClass =
  'w-full border border-[#cfd8e0] bg-white px-3.5 py-2.5 text-[15px] text-[#0a1628] outline-none transition focus:border-[#0f6e6e] focus:ring-1 focus:ring-[#0f6e6e]/40';

const DEFAULT_TEXT =
  'Your driver Karthik is on the way and will arrive in approximately 4 minutes. Vehicle number: TN45AB1234.';

export default function ComparisonPage() {
  const [voices, setVoices] = useState<StudioVoice[]>(FALLBACK_VOICES);
  const [text, setText] = useState(DEFAULT_TEXT);
  const [lang, setLang] = useState<(typeof LANGS)[number]['id']>('en');
  const [sideA, setSideA] = useState<SideState>({
    voiceId: 'jaya',
    speed: 1.0,
    audioUrl: null,
    ttfaMs: null,
    fullMs: null,
    error: '',
  });
  const [sideB, setSideB] = useState<SideState>({
    voiceId: 'kavitha',
    speed: 1.0,
    audioUrl: null,
    ttfaMs: null,
    fullMs: null,
    error: '',
  });
  const [busy, setBusy] = useState<'a' | 'b' | 'both' | null>(null);
  const [saved, setSaved] = useState<SavedComparison[]>([]);
  const [saveMsg, setSaveMsg] = useState('');
  const urls = useRef<string[]>([]);

  useEffect(() => {
    void fetchVoices(DEFAULT_TTS_SERVER).then(setVoices);
    void loadSaved();
    return () => urls.current.forEach((u) => URL.revokeObjectURL(u));
  }, []);

  const loadSaved = async () => {
    try {
      const res = await fetch(`${DEFAULT_TTS_SERVER}/studio/comparisons`, {
        cache: 'no-store',
      });
      if (!res.ok) return;
      const data = await res.json();
      setSaved((data.items as SavedComparison[]) || []);
    } catch {
      /* offline */
    }
  };

  const styleFor = (id: string) =>
    voices.find((v) => v.id === id)?.style || FALLBACK_VOICES[0].style;

  const runSide = async (
    which: 'a' | 'b',
    setter: typeof setSideA,
    state: SideState
  ) => {
    const trimmed = text.trim();
    if (!trimmed) {
      setter((s) => ({ ...s, error: 'Enter shared text first.' }));
      return;
    }
    setter((s) => ({ ...s, error: '' }));
    try {
      const result = await synthesizeSpeech({
        text: trimmed,
        voiceStyle: styleFor(state.voiceId),
        targetLang: lang,
        backend: 'edge_fast',
        server: DEFAULT_TTS_SERVER,
        sourceHint: 'comparison',
      });
      urls.current.push(result.audioUrl);
      setter((s) => ({
        ...s,
        audioUrl: result.audioUrl,
        ttfaMs: result.ttfaMs,
        fullMs: result.fullMs,
        error: '',
      }));
    } catch (e) {
      setter((s) => ({
        ...s,
        error: String(e instanceof Error ? e.message : e),
      }));
    }
  };

  const generate = async (mode: 'a' | 'b' | 'both') => {
    setBusy(mode);
    if (mode === 'a' || mode === 'both') await runSide('a', setSideA, sideA);
    if (mode === 'b' || mode === 'both') await runSide('b', setSideB, sideB);
    setBusy(null);
  };

  const swapVoices = () => {
    const a = sideA;
    const b = sideB;
    setSideA({
      ...a,
      voiceId: b.voiceId,
      speed: b.speed,
      audioUrl: null,
      ttfaMs: null,
      fullMs: null,
      error: '',
    });
    setSideB({
      ...b,
      voiceId: a.voiceId,
      speed: a.speed,
      audioUrl: null,
      ttfaMs: null,
      fullMs: null,
      error: '',
    });
  };

  const saveComparison = async () => {
    setSaveMsg('');
    try {
      const res = await fetch(`${DEFAULT_TTS_SERVER}/studio/comparisons`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text,
          lang,
          side_a: {
            voice: sideA.voiceId,
            speed: sideA.speed,
            ttfa_ms: sideA.ttfaMs,
            full_ms: sideA.fullMs,
          },
          side_b: {
            voice: sideB.voiceId,
            speed: sideB.speed,
            ttfa_ms: sideB.ttfaMs,
            full_ms: sideB.fullMs,
          },
          winner: '',
        }),
      });
      if (!res.ok) throw new Error(`Save failed (${res.status})`);
      setSaveMsg('Saved');
      await loadSaved();
    } catch (e) {
      setSaveMsg(String(e instanceof Error ? e.message : e));
    }
  };

  const reloadSaved = (item: SavedComparison) => {
    setText(item.text || '');
    if (item.lang === 'en' || item.lang === 'ta' || item.lang === 'tanglish') {
      setLang(item.lang);
    }
    setSideA((s) => ({
      ...s,
      voiceId: String(item.side_a?.voice || s.voiceId),
      speed: Number(item.side_a?.speed ?? s.speed) || 1,
      audioUrl: null,
      ttfaMs: (item.side_a?.ttfa_ms as number) ?? null,
      fullMs: (item.side_a?.full_ms as number) ?? null,
      error: '',
    }));
    setSideB((s) => ({
      ...s,
      voiceId: String(item.side_b?.voice || s.voiceId),
      speed: Number(item.side_b?.speed ?? s.speed) || 1,
      audioUrl: null,
      ttfaMs: (item.side_b?.ttfa_ms as number) ?? null,
      fullMs: (item.side_b?.full_ms as number) ?? null,
      error: '',
    }));
  };

  const SidePanel = ({
    title,
    state,
    setState,
    which,
  }: {
    title: string;
    state: SideState;
    setState: typeof setSideA;
    which: 'a' | 'b';
  }) => (
    <div className="border border-[#cfd8e0] bg-white p-4">
      <h2 className="font-[family-name:var(--font-display)] text-lg font-bold">{title}</h2>
      <div className="mt-3">
        <label className={labelClass}>Voice</label>
        <select
          value={state.voiceId}
          onChange={(e) => setState((s) => ({ ...s, voiceId: e.target.value }))}
          className={fieldClass}
        >
          {voices.map((v) => (
            <option key={v.id} value={v.id}>
              {v.label} — {v.tagline}
            </option>
          ))}
        </select>
      </div>
      <div className="mt-3">
        <span className={labelClass}>Speed</span>
        <div className="flex gap-1">
          {SPEEDS.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setState((prev) => ({ ...prev, speed: s }))}
              className={cn(
                'flex-1 border px-2 py-2 text-sm font-semibold tabular-nums',
                state.speed === s
                  ? 'border-[#0a1628] bg-[#0a1628] text-white'
                  : 'border-[#cfd8e0] bg-white hover:border-[#0f6e6e]'
              )}
            >
              {s.toFixed(1)}×
            </button>
          ))}
        </div>
      </div>
      <button
        type="button"
        onClick={() => void generate(which)}
        disabled={busy !== null}
        className="mt-3 inline-flex h-9 items-center gap-2 border border-[#cfd8e0] bg-white px-3 text-sm font-semibold hover:border-[#0f6e6e] disabled:opacity-60"
      >
        {busy === which || busy === 'both' ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
        ) : null}
        Generate Side {which.toUpperCase()}
      </button>
      {state.error ? (
        <p className="mt-2 text-xs text-[#b42318]">{state.error}</p>
      ) : null}
      {state.audioUrl ? (
        <audio
          src={state.audioUrl}
          controls
          className="mt-3 w-full"
          ref={(el) => {
            if (el) el.playbackRate = state.speed;
          }}
        />
      ) : null}
      <div className="mt-2 flex flex-wrap gap-3 text-xs text-[#5a6a7a]">
        <span>
          TTFA{' '}
          <strong className="tabular-nums text-[#0a1628]">
            {state.ttfaMs == null ? '—' : `${Math.round(state.ttfaMs)} ms`}
          </strong>
        </span>
        <span>
          Full{' '}
          <strong className="tabular-nums text-[#0a1628]">
            {state.fullMs == null ? '—' : `${Math.round(state.fullMs)} ms`}
          </strong>
        </span>
      </div>
    </div>
  );

  return (
    <ShellFrame
      title="Comparison Lab"
      subtitle="A/B voice comparison for the same utterance — measure TTFA and listen side by side."
    >
      <div className="mb-4 border border-[#cfd8e0] bg-white p-4">
        <div
          className="inline-flex border border-[#cfd8e0] bg-[#f7f9fb] p-0.5"
          role="tablist"
        >
          {LANGS.map((l) => (
            <button
              key={l.id}
              type="button"
              onClick={() => setLang(l.id)}
              className={cn(
                'px-3.5 py-1.5 text-[11px] font-semibold uppercase tracking-[0.12em]',
                lang === l.id
                  ? 'bg-[#0a1628] text-white'
                  : 'text-[#5a6a7a] hover:text-[#0a1628]'
              )}
            >
              {l.label}
            </button>
          ))}
        </div>
        <label className={cn(labelClass, 'mt-4')} htmlFor="cmp-text">
          Shared text
        </label>
        <textarea
          id="cmp-text"
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={4}
          className={cn(fieldClass, 'resize-y')}
        />
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => void generate('both')}
            disabled={busy !== null}
            className="inline-flex h-10 items-center gap-2 bg-[#0a1628] px-4 text-sm font-semibold text-white hover:bg-[#0f6e6e] disabled:opacity-60"
          >
            {busy === 'both' ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            Generate both
          </button>
          <button
            type="button"
            onClick={swapVoices}
            className="inline-flex h-10 items-center gap-2 border border-[#cfd8e0] bg-white px-4 text-sm font-semibold hover:border-[#0f6e6e]"
          >
            <ArrowLeftRight className="h-4 w-4" />
            Swap voices
          </button>
          <button
            type="button"
            onClick={() => void saveComparison()}
            className="inline-flex h-10 items-center border border-[#cfd8e0] bg-white px-4 text-sm font-semibold hover:border-[#0f6e6e]"
          >
            Save
          </button>
          {saveMsg ? <span className="self-center text-xs text-[#5a6a7a]">{saveMsg}</span> : null}
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <SidePanel title="Side A" state={sideA} setState={setSideA} which="a" />
        <SidePanel title="Side B" state={sideB} setState={setSideB} which="b" />
      </div>

      <div className="mt-6">
        <h2 className="mb-3 text-sm font-semibold">Saved comparisons</h2>
        {saved.length === 0 ? (
          <p className="text-sm text-[#94a3b0]">No saved comparisons yet.</p>
        ) : (
          <ul className="space-y-2">
            {saved.map((item, i) => (
              <li
                key={`${item.ts}-${i}`}
                className="flex flex-wrap items-center justify-between gap-2 border border-[#cfd8e0] bg-white px-4 py-3"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{item.text}</p>
                  <p className="mt-0.5 text-[11px] text-[#5a6a7a]">
                    {item.lang} · {String(item.side_a?.voice || '—')} vs{' '}
                    {String(item.side_b?.voice || '—')} ·{' '}
                    {item.ts ? new Date(item.ts).toLocaleString() : ''}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => reloadSaved(item)}
                  className="shrink-0 text-xs font-semibold text-[#0f6e6e] hover:underline"
                >
                  Reload
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </ShellFrame>
  );
}
