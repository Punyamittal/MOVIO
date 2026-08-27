'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { Loader2, Mic, MicOff, Square } from 'lucide-react';
import { cn } from '@/lib/utils';

const DEFAULT_SERVER = 'http://127.0.0.1:8001';

const VOICES = [
  {
    id: 'jaya',
    label: 'Jaya — Tamil',
    style:
      'Jaya speaks in a clear, calm, moderate-pitched voice at a moderate pace. The recording is of very high quality with no background noise.',
  },
  {
    id: 'kavitha',
    label: 'Kavitha — Tamil',
    style:
      "Kavitha's voice is clear and slightly expressive, with a moderate pitch and pace. The recording is very high quality with no background noise.",
  },
  {
    id: 'divya',
    label: 'Divya — English',
    style:
      "Divya's voice is monotone yet slightly fast in delivery, with a very close recording that almost has no background noise.",
  },
  {
    id: 'rohit',
    label: 'Rohit — English',
    style:
      'Rohit speaks in a clear male voice at a moderate pace and pitch. The recording is of very high quality with no background noise.',
  },
] as const;

type SpeechRecognitionLike = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((event: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
};

function getSpeechRecognition(): (new () => SpeechRecognitionLike) | null {
  if (typeof window === 'undefined') return null;
  const w = window as Window & {
    SpeechRecognition?: new () => SpeechRecognitionLike;
    webkitSpeechRecognition?: new () => SpeechRecognitionLike;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

const labelClass =
  'mb-2 block text-[11px] font-semibold uppercase tracking-[0.14em] text-[#5a6a7a]';
const fieldClass =
  'w-full border border-[#cfd8e0] bg-white/90 px-3.5 py-2.5 text-[15px] text-[#0a1628] outline-none transition placeholder:text-[#94a3b0] focus:border-[#0f6e6e] focus:ring-1 focus:ring-[#0f6e6e]/40';

export default function TtsDashboard({ embedded = false }: { embedded?: boolean }) {
  const [server, setServer] = useState(DEFAULT_SERVER);
  const [text, setText] = useState(
    'Unga driver 5 minutes la vandhuruvaanga. OTP 4821 share pannunga.'
  );
  const [voiceId, setVoiceId] = useState<(typeof VOICES)[number]['id']>('jaya');
  const [backend, setBackend] = useState<'win_sapi' | 'edge_fast'>('edge_fast');
  const [targetLang, setTargetLang] = useState<'tanglish' | 'en' | 'ta' | 'auto'>('tanglish');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [ttfa, setTtfa] = useState<string | number>('—');
  const [fullMs, setFullMs] = useState<string | number>('—');
  const [preMs, setPreMs] = useState<string | number>('—');
  const [normalized, setNormalized] = useState('');
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [healthy, setHealthy] = useState<boolean | null>(null);
  const [listening, setListening] = useState(false);
  const [speechSupported, setSpeechSupported] = useState(true);
  const [showServer, setShowServer] = useState(false);
  const [mode, setMode] = useState<'tts' | 'phones'>('tts');

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const audioObjectUrlRef = useRef<string | null>(null);

  const voiceStyle = VOICES.find((v) => v.id === voiceId)?.style ?? VOICES[0].style;

  useEffect(() => {
    setSpeechSupported(Boolean(getSpeechRecognition()));
  }, []);

  useEffect(() => {
    return () => {
      if (audioObjectUrlRef.current) URL.revokeObjectURL(audioObjectUrlRef.current);
      recognitionRef.current?.stop();
    };
  }, []);

  const checkHealth = useCallback(async () => {
    try {
      const base = server.replace(/\/$/, '');
      const resp = await fetch(`${base}/health`, { signal: AbortSignal.timeout(4000) });
      setHealthy(resp.ok);
    } catch {
      setHealthy(false);
    }
  }, [server]);

  useEffect(() => {
    void checkHealth();
    const id = setInterval(() => void checkHealth(), 15000);
    return () => clearInterval(id);
  }, [checkHealth]);

  const stopListening = useCallback(() => {
    recognitionRef.current?.stop();
    setListening(false);
  }, []);

  const startListening = useCallback(() => {
    const Ctor = getSpeechRecognition();
    if (!Ctor) {
      setError('Speech recognition is not supported in this browser. Type text instead.');
      return;
    }
    setError('');
    const recognition = new Ctor();
    recognition.lang = 'en-IN';
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.onresult = (event) => {
      const parts: string[] = [];
      for (let i = 0; i < event.results.length; i++) {
        parts.push(event.results[i][0].transcript);
      }
      setText(parts.join(' ').trim());
    };
    recognition.onerror = (event) => {
      setError(`Mic error: ${event.error}`);
      setListening(false);
    };
    recognition.onend = () => setListening(false);
    recognitionRef.current = recognition;
    recognition.start();
    setListening(true);
  }, []);

  const generateSpeech = async () => {
    const trimmed = text.trim();
    if (!trimmed) {
      setError('Enter text or use the mic first.');
      return;
    }
    stopListening();
    setError('');
    setLoading(true);
    setTtfa('…');
    setFullMs('…');
    setPreMs('…');
    setNormalized('');

    const base = server.replace(/\/$/, '');
    const wsUrl = base.replace(/^http/, 'ws') + '/tts/stream';
    const tClient = performance.now();
    const chunkQueue: string[] = [];
    let playing = false;
    let streamedChunks = 0;

    // Unlock autoplay during the Generate click gesture.
    const elUnlock = audioRef.current;
    if (elUnlock) {
      try {
        elUnlock.src =
          'data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAESsAACJWAAACABAAZGF0YQAAAAA=';
        await elUnlock.play();
        elUnlock.pause();
        elUnlock.currentTime = 0;
      } catch {
        /* later play() may still work after this gesture */
      }
    }

    const playNext = () => {
      if (playing) return;
      const next = chunkQueue.shift();
      if (!next) return;
      playing = true;
      if (audioObjectUrlRef.current) URL.revokeObjectURL(audioObjectUrlRef.current);
      audioObjectUrlRef.current = next;
      setAudioUrl(next);
      const el = audioRef.current;
      if (!el) {
        playing = false;
        return;
      }
      // Set src directly so play() does not race React state commit.
      el.src = next;
      el.onended = () => {
        playing = false;
        playNext();
      };
      el.onerror = () => {
        playing = false;
        playNext();
      };
      const start = () => {
        void el.play().catch((err) => {
          console.warn('autoplay blocked', err);
          playing = false;
        });
      };
      if (el.readyState >= 2) start();
      else {
        el.oncanplay = () => {
          el.oncanplay = null;
          start();
        };
      }
    };

    const enqueueB64 = (b64: string, fmt?: string) => {
      const binary = atob(b64);
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
      const mime = fmt === 'mp3' ? 'audio/mpeg' : 'audio/wav';
      chunkQueue.push(URL.createObjectURL(new Blob([bytes], { type: mime })));
      playNext();
    };

    try {
      await new Promise<void>((resolve, reject) => {
        const ws = new WebSocket(wsUrl);
        let settled = false;
        ws.onopen = () => {
          ws.send(
            JSON.stringify({
              text: trimmed,
              voice_style: voiceStyle,
              skip_llm: true,
              backend,
              target_lang: targetLang,
            })
          );
        };
        ws.onmessage = (ev) => {
          const msg = JSON.parse(ev.data as string) as {
            type: string;
            index?: number;
            ttfa_ms?: number;
            full_synthesis_ms?: number;
            preprocessing_ms?: number;
            normalized_text?: string;
            translated_text?: string;
            detected_lang?: string;
            target_lang?: string;
            translator_engine?: string;
            audio_b64?: string;
            audio_format?: string;
            detail?: string;
          };
          if (msg.type === 'chunk') {
            if (msg.index === 0) {
              const clientTtfa = Math.round(performance.now() - tClient);
              setTtfa(msg.ttfa_ms ?? clientTtfa);
              if (msg.preprocessing_ms != null) setPreMs(msg.preprocessing_ms);
              if (msg.normalized_text || msg.translated_text) {
                const parts = [];
                if (msg.detected_lang || msg.target_lang) {
                  parts.push(`${msg.detected_lang || '?'} → ${msg.target_lang || '?'}`);
                }
                if (msg.translator_engine) parts.push(`[${msg.translator_engine}]`);
                const spoken = (msg.normalized_text || msg.translated_text || '').trim();
                const translated = (msg.translated_text || '').trim();
                // Avoid duplicating when translate == normalize (fallback / passthrough)
                if (translated && spoken.toLowerCase() !== translated.toLowerCase()) {
                  parts.push(translated);
                }
                if (spoken) parts.push(spoken);
                setNormalized(parts.join(' · '));
              }
            }
            if (msg.audio_b64) {
              streamedChunks += 1;
              enqueueB64(msg.audio_b64, msg.audio_format);
            }
          } else if (msg.type === 'done') {
            setFullMs(msg.full_synthesis_ms ?? '—');
            if (msg.ttfa_ms != null) setTtfa(msg.ttfa_ms);
            if (msg.preprocessing_ms != null) setPreMs(msg.preprocessing_ms);
            if (msg.normalized_text || msg.translated_text) {
              const parts = [];
              if (msg.detected_lang || msg.target_lang) {
                parts.push(`${msg.detected_lang || '?'} → ${msg.target_lang || '?'}`);
              }
              if (msg.translator_engine) parts.push(`[${msg.translator_engine}]`);
              const spoken = (msg.normalized_text || msg.translated_text || '').trim();
              const translated = (msg.translated_text || '').trim();
              if (translated && spoken.toLowerCase() !== translated.toLowerCase()) {
                parts.push(translated);
              }
              if (spoken) parts.push(spoken);
              setNormalized(parts.join(' · '));
            }
            // Auto-play final audio when no per-chunk audio was streamed.
            if (msg.audio_b64 && streamedChunks === 0) {
              enqueueB64(msg.audio_b64, msg.audio_format);
            }
            settled = true;
            ws.close();
            resolve();
          } else if (msg.type === 'error') {
            settled = true;
            reject(new Error(msg.detail || 'stream error'));
          }
        };
        ws.onerror = () => {
          if (!settled) reject(new Error('WebSocket failed — is the TTS server running on :8001?'));
        };
        ws.onclose = () => {
          if (!settled) reject(new Error('WebSocket closed early'));
        };
      });
      setHealthy(true);
    } catch (e) {
      setError(String(e));
      setTtfa('—');
      setFullMs('—');
      setPreMs('—');
      setHealthy(false);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      className={cn(
        'relative overflow-x-hidden text-[#0a1628]',
        embedded ? 'min-h-0' : 'min-h-screen'
      )}
    >
      {/* Atmosphere */}
      {!embedded && (
        <>
          <div
            className="pointer-events-none absolute inset-0 -z-10"
            style={{
              background:
                'radial-gradient(ellipse 80% 55% at 12% -10%, rgba(15,110,110,0.18), transparent 55%), radial-gradient(ellipse 70% 50% at 100% 0%, rgba(10,22,40,0.08), transparent 50%), linear-gradient(165deg, #f4f7f9 0%, #e8eef2 48%, #dfe8ec 100%)',
            }}
          />
          <div
            className="pointer-events-none absolute inset-0 -z-10 opacity-[0.35]"
            style={{
              backgroundImage:
                'url("data:image/svg+xml,%3Csvg viewBox=\'0 0 200 200\' xmlns=\'http://www.w3.org/2000/svg\'%3E%3Cfilter id=\'n\'%3E%3CfeTurbulence type=\'fractalNoise\' baseFrequency=\'0.85\' numOctaves=\'4\' stitchTiles=\'stitch\'/%3E%3C/filter%3E%3Crect width=\'100%25\' height=\'100%25\' filter=\'url(%23n)\' opacity=\'0.45\'/%3E%3C/svg%3E")',
            }}
          />
        </>
      )}

      <main
        className={cn(
          'mx-auto w-full',
          embedded ? 'max-w-3xl px-0 pb-8 pt-0' : 'px-5 pb-16 pt-10 sm:px-6 sm:pt-14',
          !embedded && (mode === 'phones' ? 'max-w-5xl' : 'max-w-xl')
        )}
      >
        <header className={cn('mb-8', !embedded && 'animate-[fadeUp_0.7s_cubic-bezier(0.22,1,0.36,1)_both]')}>
          <div className="mb-5 flex items-center justify-between gap-3">
            <button
              type="button"
              onClick={() => setShowServer((v) => !v)}
              className="text-[11px] font-medium tracking-wide text-[#5a6a7a] underline-offset-2 transition hover:text-[#0a1628] hover:underline"
            >
              {showServer ? 'Hide endpoint' : 'Endpoint'}
            </button>
            <div className="flex items-center gap-2 text-[11px] font-medium tracking-wide text-[#5a6a7a]">
              <span
                className={cn(
                  'inline-block size-1.5 rounded-full',
                  healthy === null && 'bg-[#94a3b0]',
                  healthy === true && 'bg-[#0f6e6e]',
                  healthy === false && 'bg-[#b42318]'
                )}
                aria-hidden
              />
              {healthy === null ? 'Checking' : healthy ? 'API online' : 'API offline'}
            </div>
          </div>

          {embedded ? (
            <>
              <h1 className="font-[family-name:var(--font-display)] text-3xl font-extrabold tracking-tight">
                TTS Studio
              </h1>
              <p className="mt-2 max-w-xl text-sm leading-relaxed text-[#5a6a7a]">
                {mode === 'phones'
                  ? 'Two-phone local test — scan QR codes so both phones talk through this laptop.'
                  : 'Generate Tamil, English and Tanglish speech with live TTFA metrics.'}
              </p>
            </>
          ) : (
            <>
              <h1 className="font-[family-name:var(--font-display)] text-[clamp(2.75rem,10vw,3.75rem)] font-extrabold leading-[0.92] tracking-[-0.04em] text-[#0a1628]">
                movio
                <span className="text-[#0f6e6e]">voice</span>
              </h1>
              <p className="mt-4 max-w-[36ch] text-[15px] leading-relaxed text-[#5a6a7a]">
                {mode === 'phones'
                  ? 'Two-phone local test — scan QR codes so both phones talk through this laptop.'
                  : 'Taxi-domain TTS for Tanglish, Tamil, and English — low-latency speech for rider updates.'}
              </p>
            </>
          )}

          <div
            className="mt-6 inline-flex border border-[#cfd8e0] bg-white/70 p-0.5"
            role="tablist"
            aria-label="Dashboard mode"
          >
            <button
              type="button"
              role="tab"
              aria-selected={mode === 'tts'}
              onClick={() => setMode('tts')}
              className={cn(
                'px-3.5 py-1.5 text-[11px] font-semibold uppercase tracking-[0.12em] transition',
                mode === 'tts'
                  ? 'bg-[#0a1628] text-white'
                  : 'text-[#5a6a7a] hover:text-[#0a1628]'
              )}
            >
              Generate
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={mode === 'phones'}
              onClick={() => setMode('phones')}
              className={cn(
                'px-3.5 py-1.5 text-[11px] font-semibold uppercase tracking-[0.12em] transition',
                mode === 'phones'
                  ? 'bg-[#0a1628] text-white'
                  : 'text-[#5a6a7a] hover:text-[#0a1628]'
              )}
            >
              Two-phone test
            </button>
          </div>

          {showServer && (
            <label className="mt-6 block animate-[fadeUp_0.4s_ease_both]">
              <span className={labelClass}>Server</span>
              <input
                value={server}
                onChange={(e) => setServer(e.target.value)}
                className={fieldClass}
              />
            </label>
          )}
        </header>

        {mode === 'phones' ? (
          <div className="animate-[fadeUp_0.5s_ease_both]">
            {!healthy && (
              <p className="mb-3 text-sm text-[#b42318]" role="alert">
                TTS server looks offline. Start it with{' '}
                <code className="rounded bg-white/80 px-1.5 py-0.5 text-xs">
                  python -m phone_test
                </code>{' '}
                then refresh.
              </p>
            )}
            <iframe
              title="Two-phone voice translation test"
              src={`${server.replace(/\/$/, '')}/test/?embed=1`}
              className="h-[min(78vh,920px)] w-full border border-[#cfd8e0] bg-white/90"
            />
            <p className="mt-3 text-xs text-[#5a6a7a]">
              Phones must use the LAN IP shown inside the panel (not localhost). Same Wi-Fi as this
              laptop.
            </p>
          </div>
        ) : (
        <div className="flex flex-col gap-6 animate-[fadeUp_0.75s_cubic-bezier(0.22,1,0.36,1)_0.08s_both]">
          <div>
            <div className="mb-2 flex items-center justify-between">
              <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#5a6a7a]">
                Message
              </span>
              <button
                type="button"
                disabled={!speechSupported && !listening}
                onClick={listening ? stopListening : startListening}
                className={cn(
                  'inline-flex items-center gap-1.5 px-2 py-1 text-[11px] font-semibold uppercase tracking-[0.1em] transition',
                  listening
                    ? 'text-[#b42318]'
                    : 'text-[#5a6a7a] hover:text-[#0a1628] disabled:opacity-40'
                )}
              >
                {listening ? (
                  <>
                    <Square className="size-3 fill-current" />
                    Stop
                  </>
                ) : speechSupported ? (
                  <>
                    <Mic className="size-3" />
                    Speak
                  </>
                ) : (
                  <>
                    <MicOff className="size-3" />
                    Mic N/A
                  </>
                )}
              </button>
            </div>
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={4}
              placeholder="Type or dictate a rider message…"
              className={cn(
                fieldClass,
                'min-h-[120px] resize-y leading-relaxed',
                listening && 'border-[#0f6e6e] ring-1 ring-[#0f6e6e]/30'
              )}
            />
            {listening && (
              <p className="mt-2 text-xs font-medium text-[#0f6e6e]">Listening…</p>
            )}
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <label>
              <span className={labelClass}>Language</span>
              <select
                value={targetLang}
                onChange={(e) =>
                  setTargetLang(e.target.value as 'tanglish' | 'en' | 'ta' | 'auto')
                }
                className={cn(fieldClass, 'cursor-pointer appearance-none')}
              >
                <option value="tanglish">Tanglish</option>
                <option value="en">English</option>
                <option value="ta">Tamil</option>
                <option value="auto">Auto</option>
              </select>
            </label>
            <label>
              <span className={labelClass}>Engine</span>
              <select
                value={backend}
                onChange={(e) =>
                  setBackend(e.target.value as 'win_sapi' | 'edge_fast')
                }
                className={cn(fieldClass, 'cursor-pointer appearance-none')}
              >
                <option value="edge_fast">Neural · Edge</option>
                <option value="win_sapi">Turbo · local</option>
              </select>
            </label>
            <label>
              <span className={labelClass}>Voice</span>
              <select
                value={voiceId}
                onChange={(e) => setVoiceId(e.target.value as (typeof VOICES)[number]['id'])}
                className={cn(fieldClass, 'cursor-pointer appearance-none')}
              >
                {VOICES.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.label}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <button
            type="button"
            disabled={loading}
            onClick={() => void generateSpeech()}
            className="inline-flex h-12 w-full items-center justify-center gap-2 bg-[#0a1628] font-[family-name:var(--font-display)] text-sm font-semibold tracking-wide text-white transition hover:bg-[#0f6e6e] disabled:cursor-wait disabled:opacity-50"
          >
            {loading ? (
              <>
                <Loader2 className="size-4 animate-spin" />
                Generating…
              </>
            ) : (
              'Generate speech'
            )}
          </button>

          {error && (
            <p className="text-sm whitespace-pre-wrap text-[#b42318]" role="alert">
              {error}
            </p>
          )}

          <div className="grid grid-cols-3 gap-px border border-[#cfd8e0] bg-[#cfd8e0]">
            <div className="bg-white/80 px-4 py-4 backdrop-blur-sm">
              <span className="block text-[10px] font-semibold uppercase tracking-[0.14em] text-[#5a6a7a]">
                TTFA
              </span>
              <strong className="mt-1 block font-[family-name:var(--font-display)] text-2xl font-bold tracking-tight tabular-nums">
                {ttfa}
                <span className="ml-1 text-sm font-medium text-[#94a3b0]">ms</span>
              </strong>
            </div>
            <div className="bg-white/80 px-4 py-4 backdrop-blur-sm">
              <span className="block text-[10px] font-semibold uppercase tracking-[0.14em] text-[#5a6a7a]">
                Full synth
              </span>
              <strong className="mt-1 block font-[family-name:var(--font-display)] text-2xl font-bold tracking-tight tabular-nums">
                {fullMs}
                <span className="ml-1 text-sm font-medium text-[#94a3b0]">ms</span>
              </strong>
            </div>
            <div className="bg-white/80 px-4 py-4 backdrop-blur-sm">
              <span className="block text-[10px] font-semibold uppercase tracking-[0.14em] text-[#5a6a7a]">
                Preprocess
              </span>
              <strong className="mt-1 block font-[family-name:var(--font-display)] text-2xl font-bold tracking-tight tabular-nums">
                {preMs}
                <span className="ml-1 text-sm font-medium text-[#94a3b0]">ms</span>
              </strong>
            </div>
          </div>

          {normalized && (
            <p className="border-t border-[#cfd8e0] pt-4 text-sm leading-relaxed text-[#5a6a7a]">
              {normalized}
            </p>
          )}

          <audio ref={audioRef} src={audioUrl ?? undefined} controls className="w-full" />
        </div>
        )}
      </main>
    </div>
  );
}
