import { DEFAULT_TTS_SERVER } from '@/lib/api';

export type StudioVoice = {
  id: string;
  label: string;
  tagline: string;
  lang: string;
  style: string;
};

export type NormalizeResult = {
  ok: boolean;
  input: string;
  normalized: string;
  detected_lang: string;
  target_lang: string;
  chars: number;
  transformations: number;
  rules: {
    label: string;
    id: string;
    description: string;
    from: string;
    to: string;
  }[];
  tabs: string[];
};

export type Scenario = {
  id: string;
  category: string;
  lang: string;
  title: string;
  blurb: string;
  text: string;
  tags: string[];
};

export type SynthResult = {
  audioUrl: string;
  audioBase64: string;
  audioFormat: string;
  ttfaMs: number | null;
  fullMs: number | null;
  normalizedText: string;
  translatedText?: string;
  detectedLang?: string;
  targetLang?: string;
  backend?: string;
};

const FALLBACK_VOICES: StudioVoice[] = [
  {
    id: 'jaya',
    label: 'Jaya',
    tagline: 'Warm & friendly',
    lang: 'ta',
    style:
      'Jaya speaks in a clear, calm, moderate-pitched voice at a moderate pace. The recording is of very high quality with no background noise.',
  },
  {
    id: 'kavitha',
    label: 'Kavitha',
    tagline: 'Lively & bright',
    lang: 'ta',
    style:
      "Kavitha's voice is clear and slightly expressive, with a moderate pitch and pace. The recording is very high quality with no background noise.",
  },
  {
    id: 'divya',
    label: 'Divya',
    tagline: 'Clear English',
    lang: 'en',
    style:
      "Divya's voice is monotone yet slightly fast in delivery, with a very close recording that almost has no background noise.",
  },
  {
    id: 'rohit',
    label: 'Rohit',
    tagline: 'Clear male English',
    lang: 'en',
    style:
      'Rohit speaks in a clear male voice at a moderate pace and pitch. The recording is of very high quality with no background noise.',
  },
];

export function wordCount(text: string): number {
  return (text.trim().match(/\S+/g) || []).length;
}

export async function fetchVoices(server = DEFAULT_TTS_SERVER): Promise<StudioVoice[]> {
  try {
    const res = await fetch(`${server}/studio/voices`, { cache: 'no-store' });
    if (!res.ok) return FALLBACK_VOICES;
    const data = await res.json();
    return (data.voices as StudioVoice[]) || FALLBACK_VOICES;
  } catch {
    return FALLBACK_VOICES;
  }
}

export async function normalizeText(
  text: string,
  opts?: { target_lang?: string; use_overrides?: boolean; server?: string }
): Promise<NormalizeResult> {
  const server = opts?.server || DEFAULT_TTS_SERVER;
  const res = await fetch(`${server}/studio/normalize`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      text,
      target_lang: opts?.target_lang,
      use_overrides: opts?.use_overrides ?? true,
    }),
  });
  if (!res.ok) throw new Error(`Normalize failed (${res.status})`);
  return res.json();
}

export async function synthesizeSpeech(opts: {
  text: string;
  voiceStyle: string;
  targetLang: string;
  backend?: string;
  server?: string;
  sourceHint?: string;
}): Promise<SynthResult> {
  const server = (opts.server || DEFAULT_TTS_SERVER).replace(/\/$/, '');
  const res = await fetch(`${server}/tts`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      text: opts.text,
      voice_style: opts.voiceStyle,
      target_lang: opts.targetLang,
      backend: opts.backend || 'edge_fast',
      skip_llm: true,
      return_audio_base64: true,
    }),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || `TTS failed (${res.status})`);
  }
  const data = await res.json();
  const b64 = data.audio_base64 as string;
  const fmt = (data.audio_format as string) || 'wav';
  const mime = fmt === 'mp3' ? 'audio/mpeg' : 'audio/wav';
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  const audioUrl = URL.createObjectURL(new Blob([bytes], { type: mime }));
  return {
    audioUrl,
    audioBase64: b64,
    audioFormat: fmt,
    ttfaMs: data.ttfa_ms ?? data.metrics?.ttfa_ms ?? null,
    fullMs: data.full_synthesis_ms ?? data.metrics?.full_synthesis_ms ?? null,
    normalizedText: data.normalized_text || '',
    translatedText: data.translated_text,
    detectedLang: data.detected_lang,
    targetLang: data.target_lang,
    backend: data.backend,
  };
}

export async function fetchScenarios(server = DEFAULT_TTS_SERVER) {
  const res = await fetch(`${server}/studio/scenarios`, { cache: 'no-store' });
  if (!res.ok) throw new Error('Scenarios unavailable');
  return res.json() as Promise<{
    ok: boolean;
    categories: Record<string, number>;
    scenarios: Scenario[];
    total: number;
    acceptance_cases: number;
  }>;
}

export { FALLBACK_VOICES };
