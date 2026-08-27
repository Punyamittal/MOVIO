'use client';

import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { Loader2 } from 'lucide-react';
import { AppShell } from '@/components/app-shell';
import { DEFAULT_TTS_SERVER, fetchOverview } from '@/lib/api';
import {
  FALLBACK_VOICES,
  fetchVoices,
  normalizeText,
  synthesizeSpeech,
  wordCount,
  type StudioVoice,
} from '@/lib/studio';
import { cn } from '@/lib/utils';

const LANGS = [
  { id: 'en', label: 'English' },
  { id: 'ta', label: 'தமிழ்' },
  { id: 'tanglish', label: 'Tanglish' },
] as const;

const SPEEDS = [0.5, 1.0, 2.0] as const;

const labelClass =
  'mb-2 block text-[11px] font-semibold uppercase tracking-[0.14em] text-[#5a6a7a]';
const fieldClass =
  'w-full border border-[#cfd8e0] bg-white px-3.5 py-2.5 text-[15px] text-[#0a1628] outline-none transition placeholder:text-[#94a3b0] focus:border-[#0f6e6e] focus:ring-1 focus:ring-[#0f6e6e]/40';

const DEFAULT_TEXT =
  'Thank you for booking with Movio. Your cab has been confirmed. Pickup at Chennai Central, drop at T Nagar. Fare: ₹185. Booking ID: TN45AB1234.';

export default function StudioWorkspace() {
  const searchParams = useSearchParams();
  const [voices, setVoices] = useState<StudioVoice[]>(FALLBACK_VOICES);
  const [text, setText] = useState(DEFAULT_TEXT);
  const [lang, setLang] = useState<(typeof LANGS)[number]['id']>('en');
  const [voiceId, setVoiceId] = useState('jaya');
  const [speed, setSpeed] = useState(1.0);
  const [historyCount, setHistoryCount] = useState<number | null>(null);
  const [online, setOnline] = useState(false);
  const [statusLabel, setStatusLabel] = useState('Engine status');
  const [statusDetail, setStatusDetail] = useState('Connect TTS runtime on :8001');
  const [version, setVersion] = useState('v1.1 prototype');
  const [loading, setLoading] = useState(false);
  const [normalizing, setNormalizing] = useState(false);
  const [error, setError] = useState('');
  const [normalizedPreview, setNormalizedPreview] = useState('');
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [ttfaMs, setTtfaMs] = useState<number | null>(null);
  const [fullMs, setFullMs] = useState<number | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const objectUrlRef = useRef<string | null>(null);

  useEffect(() => {
    const qText = searchParams.get('text');
    const qLang = searchParams.get('lang');
    if (qText) setText(qText);
    if (qLang === 'en' || qLang === 'ta' || qLang === 'tanglish') setLang(qLang);
  }, [searchParams]);

  useEffect(() => {
    void fetchVoices(DEFAULT_TTS_SERVER).then(setVoices);
    void fetchOverview(DEFAULT_TTS_SERVER)
      .then((o) => {
        setHistoryCount(o.kpis.syntheses);
        setOnline(Boolean(o.status.engine_online));
        setStatusLabel(o.status.label || 'Engine online');
        setStatusDetail(o.status.detail || 'TTS runtime ready');
        setVersion(o.version || 'v1.1 prototype');
      })
      .catch(() => {
        setOnline(false);
        setStatusLabel('Engine offline');
        setStatusDetail('Cannot reach TTS API on :8001');
      });
  }, []);

  useEffect(() => {
    return () => {
      if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
    };
  }, []);

  useEffect(() => {
    if (audioRef.current) audioRef.current.playbackRate = speed;
  }, [speed, audioUrl]);

  const voiceStyle =
    voices.find((v) => v.id === voiceId)?.style || FALLBACK_VOICES[0].style;

  const playResult = (url: string) => {
    if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
    objectUrlRef.current = url;
    setAudioUrl(url);
    requestAnimationFrame(() => {
      const el = audioRef.current;
      if (!el) return;
      el.playbackRate = speed;
      void el.play().catch(() => undefined);
    });
  };

  const onGenerate = async () => {
    const trimmed = text.trim();
    if (!trimmed) {
      setError('Enter text to synthesize.');
      return;
    }
    setLoading(true);
    setError('');
    try {
      const result = await synthesizeSpeech({
        text: trimmed,
        voiceStyle,
        targetLang: lang,
        backend: 'edge_fast',
        server: DEFAULT_TTS_SERVER,
        sourceHint: 'studio',
      });
      setTtfaMs(result.ttfaMs);
      setFullMs(result.fullMs);
      if (result.normalizedText) setNormalizedPreview(result.normalizedText);
      playResult(result.audioUrl);
      setHistoryCount((n) => (n == null ? 1 : n + 1));
      setOnline(true);
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setLoading(false);
    }
  };

  const onNormalize = async () => {
    const trimmed = text.trim();
    if (!trimmed) {
      setError('Enter text to normalize.');
      return;
    }
    setNormalizing(true);
    setError('');
    try {
      const result = await normalizeText(trimmed, {
        target_lang: lang,
        server: DEFAULT_TTS_SERVER,
      });
      setNormalizedPreview(result.normalized);
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setNormalizing(false);
    }
  };

  const chars = text.length;
  const words = wordCount(text);

  return (
    <AppShell
      online={online}
      statusLabel={statusLabel}
      statusDetail={statusDetail}
      version={version}
    >
      <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="font-[family-name:var(--font-display)] text-3xl font-extrabold tracking-tight">
            TTS Studio
          </h1>
          <p className="mt-2 max-w-2xl text-sm leading-relaxed text-[#5a6a7a]">
            Generate natural Tamil, English and Tanglish speech for taxi voice agents — target p99
            ≤ 500ms.
          </p>
        </div>
        <span className="inline-flex items-center border border-[#cfd8e0] bg-white px-3 py-1.5 text-xs font-semibold text-[#0a1628]">
          History
          <span className="ml-2 tabular-nums text-[#0f6e6e]">
            {historyCount == null ? '—' : historyCount}
          </span>
        </span>
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_16rem]">
        <div className="space-y-4">
          <div className="border border-[#cfd8e0] bg-white p-4">
            <div
              className="inline-flex border border-[#cfd8e0] bg-[#f7f9fb] p-0.5"
              role="tablist"
              aria-label="Language"
            >
              {LANGS.map((l) => (
                <button
                  key={l.id}
                  type="button"
                  role="tab"
                  aria-selected={lang === l.id}
                  onClick={() => setLang(l.id)}
                  className={cn(
                    'px-3.5 py-1.5 text-[11px] font-semibold uppercase tracking-[0.12em] transition',
                    lang === l.id
                      ? 'bg-[#0a1628] text-white'
                      : 'text-[#5a6a7a] hover:text-[#0a1628]'
                  )}
                >
                  {l.label}
                </button>
              ))}
            </div>

            <label className={cn(labelClass, 'mt-4')} htmlFor="studio-text">
              Utterance
            </label>
            <textarea
              id="studio-text"
              value={text}
              maxLength={5000}
              onChange={(e) => setText(e.target.value)}
              rows={6}
              className={cn(fieldClass, 'min-h-[9rem] resize-y')}
              placeholder="Type rider or agent text…"
            />
            <div className="mt-2 flex justify-between text-[11px] text-[#94a3b0]">
              <span>
                {chars}/5000 · {words} words
              </span>
              <span>Backend edge_fast</span>
            </div>

            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <div>
                <label className={labelClass} htmlFor="studio-voice">
                  Voice
                </label>
                <select
                  id="studio-voice"
                  value={voiceId}
                  onChange={(e) => setVoiceId(e.target.value)}
                  className={fieldClass}
                >
                  {voices.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.label} — {v.tagline}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <span className={labelClass}>Speed</span>
                <div className="flex gap-1">
                  {SPEEDS.map((s) => (
                    <button
                      key={s}
                      type="button"
                      onClick={() => setSpeed(s)}
                      className={cn(
                        'flex-1 border px-2 py-2.5 text-sm font-semibold tabular-nums transition',
                        speed === s
                          ? 'border-[#0a1628] bg-[#0a1628] text-white'
                          : 'border-[#cfd8e0] bg-white text-[#0a1628] hover:border-[#0f6e6e]'
                      )}
                    >
                      {s.toFixed(1)}×
                    </button>
                  ))}
                </div>
              </div>
            </div>

            <div className="mt-4 flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => void onGenerate()}
                disabled={loading}
                className="inline-flex h-10 items-center gap-2 bg-[#0a1628] px-4 text-sm font-semibold text-white transition hover:bg-[#0f6e6e] disabled:opacity-60"
              >
                {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                Generate speech
              </button>
              <button
                type="button"
                onClick={() => void onNormalize()}
                disabled={normalizing}
                className="inline-flex h-10 items-center gap-2 border border-[#cfd8e0] bg-white px-4 text-sm font-semibold text-[#0a1628] transition hover:border-[#0f6e6e] disabled:opacity-60"
              >
                {normalizing ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                Normalize
              </button>
            </div>

            {error ? (
              <p className="mt-3 border border-[#f0c2bd] bg-[#fff5f4] px-3 py-2 text-sm text-[#b42318]">
                {error}
              </p>
            ) : null}

            {normalizedPreview ? (
              <div className="mt-4 border border-[#cfd8e0] bg-[#f7f9fb] px-3 py-3">
                <p className={labelClass}>Normalized</p>
                <p className="text-sm leading-relaxed text-[#0a1628]">{normalizedPreview}</p>
              </div>
            ) : null}

            {audioUrl ? (
              <div className="mt-4 space-y-2">
                <audio ref={audioRef} src={audioUrl} controls className="w-full" />
                <div className="flex flex-wrap gap-3 text-xs text-[#5a6a7a]">
                  <span>
                    TTFA{' '}
                    <strong className="tabular-nums text-[#0a1628]">
                      {ttfaMs == null ? '—' : `${Math.round(ttfaMs)} ms`}
                    </strong>
                  </span>
                  <span>
                    Full{' '}
                    <strong className="tabular-nums text-[#0a1628]">
                      {fullMs == null ? '—' : `${Math.round(fullMs)} ms`}
                    </strong>
                  </span>
                </div>
              </div>
            ) : null}
          </div>

          <p className="border border-[#cfd8e0] bg-white px-4 py-3 text-sm text-[#5a6a7a]">
            <span className="font-semibold text-[#0a1628]">Pro tip · </span>
            Booking IDs and OTPs are spoken digit-by-digit so riders hear every character clearly.
            Try Normalize before Generate to preview the spoken form.
          </p>
        </div>

        <aside className="space-y-3">
          {[
            { label: 'Target p99', value: '500ms' },
            { label: 'Concurrency', value: '15–20' },
            { label: 'Voices', value: '7' },
            { label: 'Languages', value: '3' },
          ].map((kpi) => (
            <div key={kpi.label} className="border border-[#cfd8e0] bg-white px-4 py-3">
              <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#5a6a7a]">
                {kpi.label}
              </p>
              <p className="mt-1 font-[family-name:var(--font-display)] text-xl font-bold">
                {kpi.value}
              </p>
            </div>
          ))}
        </aside>
      </div>
    </AppShell>
  );
}
