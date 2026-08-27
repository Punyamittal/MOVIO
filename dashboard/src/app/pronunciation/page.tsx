'use client';

import { useEffect, useRef, useState } from 'react';
import { Loader2, Upload } from 'lucide-react';
import { ShellFrame } from '@/components/section-frame';
import { DEFAULT_TTS_SERVER } from '@/lib/api';
import { normalizeText } from '@/lib/studio';
import { cn } from '@/lib/utils';

type LexEntry = { word: string; spoken: string; lang?: string; note?: string; source?: string };

const labelClass =
  'mb-2 block text-[11px] font-semibold uppercase tracking-[0.14em] text-[#5a6a7a]';
const fieldClass =
  'w-full border border-[#cfd8e0] bg-white px-3.5 py-2.5 text-[15px] text-[#0a1628] outline-none transition focus:border-[#0f6e6e] focus:ring-1 focus:ring-[#0f6e6e]/40';

export default function PronunciationPage() {
  const [base, setBase] = useState<LexEntry[]>([]);
  const [overrides, setOverrides] = useState<LexEntry[]>([]);
  const [word, setWord] = useState('');
  const [spoken, setSpoken] = useState('');
  const [tester, setTester] = useState(
    'Meet the driver near T Nagar. Booking TN45AB1234. OTP 4821.'
  );
  const [testerOut, setTesterOut] = useState('');
  const [loading, setLoading] = useState(false);
  const [testing, setTesting] = useState(false);
  const [error, setError] = useState('');
  const fileRef = useRef<HTMLInputElement | null>(null);

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const res = await fetch(`${DEFAULT_TTS_SERVER}/studio/lexicon`, {
        cache: 'no-store',
      });
      if (!res.ok) throw new Error(`Lexicon unavailable (${res.status})`);
      const data = await res.json();
      setBase((data.base as LexEntry[]) || []);
      setOverrides((data.overrides as LexEntry[]) || []);
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const addOverride = async () => {
    if (!word.trim() || !spoken.trim()) {
      setError('Word and spoken form are required.');
      return;
    }
    setError('');
    try {
      const res = await fetch(`${DEFAULT_TTS_SERVER}/studio/lexicon`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          word: word.trim(),
          spoken: spoken.trim(),
          lang: 'all',
        }),
      });
      if (!res.ok) throw new Error(`Add failed (${res.status})`);
      const data = await res.json();
      setOverrides((data.overrides as LexEntry[]) || []);
      setWord('');
      setSpoken('');
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    }
  };

  const clearAll = async () => {
    if (!confirm('Clear all pronunciation overrides?')) return;
    try {
      const res = await fetch(`${DEFAULT_TTS_SERVER}/studio/lexicon`, {
        method: 'DELETE',
      });
      if (!res.ok) throw new Error(`Clear failed (${res.status})`);
      const data = await res.json();
      setOverrides((data.overrides as LexEntry[]) || []);
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    }
  };

  const runTester = async () => {
    setTesting(true);
    setError('');
    try {
      const result = await normalizeText(tester, {
        use_overrides: true,
        server: DEFAULT_TTS_SERVER,
      });
      setTesterOut(result.normalized);
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setTesting(false);
    }
  };

  const exportJson = () => {
    const blob = new Blob([JSON.stringify(overrides, null, 2)], {
      type: 'application/json',
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'lexicon-overrides.json';
    a.click();
    URL.revokeObjectURL(url);
  };

  const importJson = async (file: File) => {
    try {
      const parsed = JSON.parse(await file.text()) as LexEntry[];
      if (!Array.isArray(parsed)) throw new Error('Expected an array of overrides');
      for (const item of parsed) {
        if (!item.word || !item.spoken) continue;
        await fetch(`${DEFAULT_TTS_SERVER}/studio/lexicon`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            word: item.word,
            spoken: item.spoken,
            lang: item.lang || 'all',
            note: item.note || '',
          }),
        });
      }
      await load();
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    }
  };

  return (
    <ShellFrame
      title="Pronunciation"
      subtitle="Custom overrides for place names, brands and domain terms — layered on the base lexicon."
    >
      {error ? (
        <p className="mb-4 border border-[#f0c2bd] bg-[#fff5f4] px-3 py-2 text-sm text-[#b42318]">
          {error}
        </p>
      ) : null}

      <div className="mb-4 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading}
          className="inline-flex h-9 items-center gap-2 border border-[#cfd8e0] bg-white px-3 text-sm font-semibold hover:border-[#0f6e6e]"
        >
          {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
          Refresh
        </button>
        <button
          type="button"
          onClick={exportJson}
          className="inline-flex h-9 items-center border border-[#cfd8e0] bg-white px-3 text-sm font-semibold hover:border-[#0f6e6e]"
        >
          Export JSON
        </button>
        <button
          type="button"
          onClick={() => fileRef.current?.click()}
          className="inline-flex h-9 items-center gap-2 border border-[#cfd8e0] bg-white px-3 text-sm font-semibold hover:border-[#0f6e6e]"
        >
          <Upload className="h-3.5 w-3.5" />
          Import JSON
        </button>
        <input
          ref={fileRef}
          type="file"
          accept="application/json,.json"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void importJson(f);
            e.target.value = '';
          }}
        />
        <button
          type="button"
          onClick={() => void clearAll()}
          className="inline-flex h-9 items-center border border-[#f0c2bd] bg-white px-3 text-sm font-semibold text-[#b42318] hover:bg-[#fff5f4]"
        >
          Clear all overrides
        </button>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <section className="border border-[#cfd8e0] bg-white p-4">
          <h2 className="text-sm font-semibold">
            Base lexicon{' '}
            <span className="font-normal text-[#94a3b0]">({base.length})</span>
          </h2>
          <ul className="mt-3 max-h-64 space-y-1 overflow-y-auto text-sm">
            {base.slice(0, 80).map((e) => (
              <li
                key={`b-${e.word}`}
                className="flex justify-between gap-2 border-b border-[#e8eef2] py-1.5"
              >
                <span className="font-medium">{e.word}</span>
                <span className="text-[#5a6a7a]">{e.spoken}</span>
              </li>
            ))}
            {base.length === 0 ? (
              <li className="text-[#94a3b0]">No base entries loaded.</li>
            ) : null}
          </ul>
        </section>

        <section className="border border-[#cfd8e0] bg-white p-4">
          <h2 className="text-sm font-semibold">
            Overrides{' '}
            <span className="font-normal text-[#94a3b0]">({overrides.length})</span>
          </h2>
          <ul className="mt-3 max-h-48 space-y-1 overflow-y-auto text-sm">
            {overrides.map((e) => (
              <li
                key={`o-${e.word}`}
                className="flex justify-between gap-2 border-b border-[#e8eef2] py-1.5"
              >
                <span className="font-medium">{e.word}</span>
                <span className="text-[#0f6e6e]">{e.spoken}</span>
              </li>
            ))}
            {overrides.length === 0 ? (
              <li className="text-[#94a3b0]">No overrides yet.</li>
            ) : null}
          </ul>

          <div className="mt-4 grid gap-2 sm:grid-cols-2">
            <div>
              <label className={labelClass} htmlFor="lex-word">
                Word
              </label>
              <input
                id="lex-word"
                value={word}
                onChange={(e) => setWord(e.target.value)}
                className={fieldClass}
                placeholder="T Nagar"
              />
            </div>
            <div>
              <label className={labelClass} htmlFor="lex-spoken">
                Spoken as
              </label>
              <input
                id="lex-spoken"
                value={spoken}
                onChange={(e) => setSpoken(e.target.value)}
                className={fieldClass}
                placeholder="tee nagar"
              />
            </div>
          </div>
          <button
            type="button"
            onClick={() => void addOverride()}
            className="mt-3 inline-flex h-9 items-center bg-[#0a1628] px-3 text-sm font-semibold text-white hover:bg-[#0f6e6e]"
          >
            Add override
          </button>
        </section>
      </div>

      <section className="mt-4 border border-[#cfd8e0] bg-white p-4">
        <h2 className="text-sm font-semibold">Live tester</h2>
        <p className="mt-1 text-xs text-[#5a6a7a]">
          Normalize with overrides applied — preview the spoken form before synthesis.
        </p>
        <textarea
          value={tester}
          onChange={(e) => setTester(e.target.value)}
          rows={3}
          className={cn(fieldClass, 'mt-3 resize-y')}
        />
        <button
          type="button"
          onClick={() => void runTester()}
          disabled={testing}
          className="mt-2 inline-flex h-9 items-center gap-2 bg-[#0a1628] px-3 text-sm font-semibold text-white hover:bg-[#0f6e6e] disabled:opacity-60"
        >
          {testing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
          Normalize with overrides
        </button>
        {testerOut ? (
          <p className="mt-3 border border-[#cfd8e0] bg-[#f7f9fb] px-3 py-2 text-sm leading-relaxed">
            {testerOut}
          </p>
        ) : null}
      </section>
    </ShellFrame>
  );
}
