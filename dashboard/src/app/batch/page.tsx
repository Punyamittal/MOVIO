'use client';

import { useEffect, useRef, useState } from 'react';
import { Loader2, Plus, Trash2 } from 'lucide-react';
import { ShellFrame } from '@/components/section-frame';
import { DEFAULT_TTS_SERVER } from '@/lib/api';
import {
  FALLBACK_VOICES,
  fetchVoices,
  synthesizeSpeech,
  type StudioVoice,
} from '@/lib/studio';
import { cn } from '@/lib/utils';

const SPEEDS = [0.5, 1.0, 2.0] as const;

const DEFAULT_ITEMS = [
  {
    lang: 'en',
    text: 'Thank you for booking with Movio. Booking ID: TN45AB1234.',
  },
  {
    lang: 'ta',
    text: 'உங்கள் pickup location Chennai Central-ல இருக்கா?',
  },
  {
    lang: 'en',
    text: 'Driver Karthik will arrive in 4 minutes. Phone: 9876543210.',
  },
  {
    lang: 'en',
    text: 'Your OTP is 4821. Total fare: ₹250.50.',
  },
];

type BatchItem = {
  id: string;
  text: string;
  lang: string;
  audioUrl?: string;
  ttfaMs?: number | null;
  fullMs?: number | null;
  error?: string;
};

const labelClass =
  'mb-2 block text-[11px] font-semibold uppercase tracking-[0.14em] text-[#5a6a7a]';
const fieldClass =
  'w-full border border-[#cfd8e0] bg-white px-3.5 py-2.5 text-[15px] text-[#0a1628] outline-none transition focus:border-[#0f6e6e] focus:ring-1 focus:ring-[#0f6e6e]/40';

function uid() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export default function BatchPage() {
  const [voices, setVoices] = useState<StudioVoice[]>(FALLBACK_VOICES);
  const [voiceId, setVoiceId] = useState('jaya');
  const [speed, setSpeed] = useState(1.0);
  const [items, setItems] = useState<BatchItem[]>(() =>
    DEFAULT_ITEMS.map((d) => ({ id: uid(), ...d }))
  );
  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkText, setBulkText] = useState('');
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState('');
  const objectUrls = useRef<string[]>([]);

  useEffect(() => {
    void fetchVoices(DEFAULT_TTS_SERVER).then(setVoices);
    return () => {
      objectUrls.current.forEach((u) => URL.revokeObjectURL(u));
    };
  }, []);

  const voiceStyle =
    voices.find((v) => v.id === voiceId)?.style || FALLBACK_VOICES[0].style;

  const updateItem = (id: string, patch: Partial<BatchItem>) => {
    setItems((prev) => prev.map((it) => (it.id === id ? { ...it, ...patch } : it)));
  };

  const generateAll = async () => {
    setRunning(true);
    setProgress('');
    for (let i = 0; i < items.length; i++) {
      const it = items[i];
      const trimmed = it.text.trim();
      if (!trimmed) continue;
      setProgress(`Synthesizing ${i + 1} / ${items.length}`);
      try {
        const result = await synthesizeSpeech({
          text: trimmed,
          voiceStyle,
          targetLang: it.lang || 'en',
          backend: 'edge_fast',
          server: DEFAULT_TTS_SERVER,
          sourceHint: 'batch',
        });
        objectUrls.current.push(result.audioUrl);
        updateItem(it.id, {
          audioUrl: result.audioUrl,
          ttfaMs: result.ttfaMs,
          fullMs: result.fullMs,
          error: undefined,
        });
      } catch (e) {
        updateItem(it.id, {
          error: String(e instanceof Error ? e.message : e),
        });
      }
    }
    setProgress('');
    setRunning(false);
  };

  const downloadManifest = () => {
    const payload = {
      voice: voiceId,
      speed,
      backend: 'edge_fast',
      generated_at: new Date().toISOString(),
      items: items.map((it) => ({
        text: it.text,
        lang: it.lang,
        ttfa_ms: it.ttfaMs ?? null,
        full_ms: it.fullMs ?? null,
        error: it.error || null,
        has_audio: Boolean(it.audioUrl),
      })),
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], {
      type: 'application/json',
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'batch-manifest.json';
    a.click();
    URL.revokeObjectURL(url);
  };

  const applyBulk = () => {
    const lines = bulkText
      .split(/\r?\n/)
      .map((l) => l.trim())
      .filter(Boolean);
    if (!lines.length) return;
    setItems(lines.map((text) => ({ id: uid(), text, lang: 'en' })));
    setBulkOpen(false);
    setBulkText('');
  };

  return (
    <ShellFrame
      title="Batch Synthesis"
      subtitle="Bulk generation for scripts and contact-center scenario packs. Each item uses the studio /tts path."
    >
      <div className="mb-4 flex flex-wrap items-end gap-3 border border-[#cfd8e0] bg-white p-4">
        <div className="min-w-[12rem] flex-1">
          <label className={labelClass} htmlFor="batch-voice">
            Voice
          </label>
          <select
            id="batch-voice"
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
                  'border px-3 py-2.5 text-sm font-semibold tabular-nums',
                  speed === s
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
          onClick={() => void generateAll()}
          disabled={running || items.length === 0}
          className="inline-flex h-10 items-center gap-2 bg-[#0a1628] px-4 text-sm font-semibold text-white hover:bg-[#0f6e6e] disabled:opacity-60"
        >
          {running ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          Generate all
        </button>
        <button
          type="button"
          onClick={downloadManifest}
          className="inline-flex h-10 items-center border border-[#cfd8e0] bg-white px-4 text-sm font-semibold hover:border-[#0f6e6e]"
        >
          Download JSON manifest
        </button>
      </div>

      {progress ? <p className="mb-3 text-sm text-[#0f6e6e]">{progress}</p> : null}

      <div className="space-y-3">
        {items.map((it, idx) => (
          <div key={it.id} className="border border-[#cfd8e0] bg-white p-4">
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#5a6a7a]">
                Item {idx + 1}
              </p>
              <div className="flex items-center gap-2">
                <select
                  value={it.lang}
                  onChange={(e) => updateItem(it.id, { lang: e.target.value })}
                  className="border border-[#cfd8e0] bg-white px-2 py-1 text-xs font-semibold"
                >
                  <option value="en">EN</option>
                  <option value="ta">TA</option>
                  <option value="tanglish">Tanglish</option>
                </select>
                <button
                  type="button"
                  onClick={() => setItems((prev) => prev.filter((x) => x.id !== it.id))}
                  className="text-[#94a3b0] hover:text-[#b42318]"
                  aria-label="Remove item"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            </div>
            <textarea
              value={it.text}
              onChange={(e) => updateItem(it.id, { text: e.target.value })}
              rows={2}
              className={cn(fieldClass, 'resize-y')}
            />
            {it.error ? (
              <p className="mt-2 text-xs text-[#b42318]">{it.error}</p>
            ) : null}
            {it.audioUrl ? (
              <div className="mt-3 space-y-1">
                <audio
                  src={it.audioUrl}
                  controls
                  className="w-full"
                  ref={(el) => {
                    if (el) el.playbackRate = speed;
                  }}
                />
                <p className="text-xs text-[#5a6a7a]">
                  TTFA{' '}
                  <strong className="tabular-nums text-[#0a1628]">
                    {it.ttfaMs == null ? '—' : `${Math.round(it.ttfaMs)} ms`}
                  </strong>
                  {it.fullMs != null ? (
                    <>
                      {' '}
                      · Full{' '}
                      <strong className="tabular-nums text-[#0a1628]">
                        {Math.round(it.fullMs)} ms
                      </strong>
                    </>
                  ) : null}
                </p>
              </div>
            ) : null}
          </div>
        ))}
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() =>
            setItems((prev) => [...prev, { id: uid(), text: '', lang: 'en' }])
          }
          className="inline-flex h-10 items-center gap-2 border border-[#cfd8e0] bg-white px-4 text-sm font-semibold hover:border-[#0f6e6e]"
        >
          <Plus className="h-4 w-4" />
          Add item
        </button>
        <button
          type="button"
          onClick={() => setBulkOpen((v) => !v)}
          className="inline-flex h-10 items-center border border-[#cfd8e0] bg-white px-4 text-sm font-semibold hover:border-[#0f6e6e]"
        >
          Bulk paste
        </button>
      </div>

      {bulkOpen ? (
        <div className="mt-3 border border-[#cfd8e0] bg-white p-4">
          <label className={labelClass} htmlFor="bulk">
            One utterance per line
          </label>
          <textarea
            id="bulk"
            value={bulkText}
            onChange={(e) => setBulkText(e.target.value)}
            rows={6}
            className={cn(fieldClass, 'resize-y')}
            placeholder="Paste lines…"
          />
          <button
            type="button"
            onClick={applyBulk}
            className="mt-2 inline-flex h-9 items-center bg-[#0a1628] px-3 text-sm font-semibold text-white hover:bg-[#0f6e6e]"
          >
            Replace list
          </button>
        </div>
      ) : null}
    </ShellFrame>
  );
}
