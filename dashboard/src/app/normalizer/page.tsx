'use client';

import { useMemo, useState } from 'react';
import { Copy, Loader2 } from 'lucide-react';
import { ShellFrame } from '@/components/section-frame';
import { DEFAULT_TTS_SERVER } from '@/lib/api';
import { normalizeText, type NormalizeResult } from '@/lib/studio';
import { cn } from '@/lib/utils';

const TABS = [
  'Booking ID',
  'OTP',
  'Phone',
  'Time',
  'Currency+Distance',
  'Tanglish',
] as const;

const SAMPLES: Record<(typeof TABS)[number], string> = {
  'Booking ID': 'Your booking ID is TN45AB1234. Please keep it for reference.',
  OTP: 'Your OTP for starting the trip is 4821. Please share this with the driver.',
  Phone: 'Please call the customer at 9876543210 before arriving at the pickup.',
  Time: 'Your driver will arrive at 7:30 PM. The booking was made on 15/03/2026.',
  'Currency+Distance':
    'The final fare is ₹250.50 for a route change of 3.2 km from the estimate.',
  Tanglish: 'Unga pickup Chennai Central-la irukka? Driver 5 minutes la vandhuruvaanga.',
};

const labelClass =
  'mb-2 block text-[11px] font-semibold uppercase tracking-[0.14em] text-[#5a6a7a]';
const fieldClass =
  'w-full border border-[#cfd8e0] bg-white px-3.5 py-2.5 text-[15px] text-[#0a1628] outline-none transition placeholder:text-[#94a3b0] focus:border-[#0f6e6e] focus:ring-1 focus:ring-[#0f6e6e]/40';

export default function NormalizerPage() {
  const [tab, setTab] = useState<(typeof TABS)[number]>('Booking ID');
  const [raw, setRaw] = useState(SAMPLES['Booking ID']);
  const [result, setResult] = useState<NormalizeResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState(false);

  const filteredRules = useMemo(() => {
    if (!result?.rules?.length) return [];
    return result.rules.filter((r) => r.label === tab || tab === 'Tanglish');
  }, [result, tab]);

  const runNormalize = async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed) {
      setError('Enter text to normalize.');
      return;
    }
    setLoading(true);
    setError('');
    try {
      const data = await normalizeText(trimmed, { server: DEFAULT_TTS_SERVER });
      setResult(data);
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setLoading(false);
    }
  };

  const onTab = (next: (typeof TABS)[number]) => {
    setTab(next);
    setRaw(SAMPLES[next]);
    setResult(null);
    setCopied(false);
  };

  const copyOut = async () => {
    if (!result?.normalized) return;
    await navigator.clipboard.writeText(result.normalized);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const highlight =
    tab === 'Booking ID'
      ? 'Booking IDs and plates are spelled character-by-character for clear TTS.'
      : tab === 'OTP'
        ? 'OTPs and short codes expand digit-by-digit so each digit is spoken distinctly.'
        : tab === 'Phone'
          ? 'Phone numbers expand digit-by-digit for natural spoken delivery.'
          : tab === 'Time'
            ? 'Clock times and dates become natural spoken calendar forms.'
            : tab === 'Currency+Distance'
              ? 'Rupee amounts and kilometre distances become spoken units.'
              : 'Tanglish / lexicon overrides polish place names and code-mixed phrases.';

  return (
    <ShellFrame
      title="Text Normalizer"
      subtitle="Context-aware taxi-domain normalization — booking IDs, OTPs, phones, times, currency and Tanglish."
    >
      <div className="mb-4 flex flex-wrap gap-1 border border-[#cfd8e0] bg-white p-1">
        {TABS.map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => onTab(t)}
            className={cn(
              'px-3 py-1.5 text-xs font-semibold transition',
              tab === t
                ? 'bg-[#0a1628] text-white'
                : 'text-[#5a6a7a] hover:bg-[#f7f9fb] hover:text-[#0a1628]'
            )}
          >
            {t}
          </button>
        ))}
      </div>

      <p className="mb-4 border-l-2 border-[#0f6e6e] bg-white px-3 py-2 text-sm text-[#5a6a7a]">
        {highlight}
      </p>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="border border-[#cfd8e0] bg-white p-4">
          <label className={labelClass} htmlFor="norm-raw">
            Raw input
          </label>
          <textarea
            id="norm-raw"
            value={raw}
            onChange={(e) => setRaw(e.target.value)}
            rows={8}
            className={cn(fieldClass, 'min-h-[10rem] resize-y')}
          />
          <button
            type="button"
            onClick={() => void runNormalize(raw)}
            disabled={loading}
            className="mt-3 inline-flex h-10 items-center gap-2 bg-[#0a1628] px-4 text-sm font-semibold text-white hover:bg-[#0f6e6e] disabled:opacity-60"
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            Normalize
          </button>
        </div>

        <div className="border border-[#cfd8e0] bg-white p-4">
          <div className="mb-2 flex items-center justify-between">
            <label className={labelClass} htmlFor="norm-out">
              Normalized output
            </label>
            <button
              type="button"
              onClick={() => void copyOut()}
              disabled={!result?.normalized}
              className="inline-flex items-center gap-1 text-xs font-semibold text-[#0f6e6e] disabled:opacity-40"
            >
              <Copy className="h-3.5 w-3.5" />
              {copied ? 'Copied' : 'Copy'}
            </button>
          </div>
          <textarea
            id="norm-out"
            readOnly
            value={result?.normalized || ''}
            rows={8}
            className={cn(fieldClass, 'min-h-[10rem] resize-y bg-[#f7f9fb]')}
            placeholder="Normalized text appears here…"
          />
          {result ? (
            <p className="mt-2 text-xs text-[#5a6a7a]">
              <span className="font-semibold text-[#0a1628]">{result.transformations}</span>{' '}
              transformation{result.transformations === 1 ? '' : 's'} · detected{' '}
              {result.detected_lang || '—'}
            </p>
          ) : null}
        </div>
      </div>

      {error ? (
        <p className="mt-4 border border-[#f0c2bd] bg-[#fff5f4] px-3 py-2 text-sm text-[#b42318]">
          {error}
        </p>
      ) : null}

      {result?.rules?.length ? (
        <div className="mt-4">
          <h2 className="mb-3 text-sm font-semibold">Rule breakdown</h2>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {(filteredRules.length ? filteredRules : result.rules).map((rule, i) => (
              <div key={`${rule.id}-${i}`} className="border border-[#cfd8e0] bg-white px-4 py-3">
                <p className="text-sm font-semibold">{rule.label}</p>
                <p className="mt-1 text-xs leading-relaxed text-[#5a6a7a]">{rule.description}</p>
                <p className="mt-2 text-xs">
                  <span className="text-[#94a3b0]">{rule.from}</span>
                  <span className="mx-1.5 text-[#0f6e6e]">→</span>
                  <span className="font-medium text-[#0a1628]">{rule.to}</span>
                </p>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </ShellFrame>
  );
}
