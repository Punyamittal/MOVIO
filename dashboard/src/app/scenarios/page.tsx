'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { ShellFrame } from '@/components/section-frame';
import { DEFAULT_TTS_SERVER } from '@/lib/api';
import { fetchScenarios, type Scenario } from '@/lib/studio';
import { cn } from '@/lib/utils';

const LANG_FILTERS = [
  { id: 'all', label: 'All' },
  { id: 'english', label: 'English' },
  { id: 'tamil', label: 'Tamil' },
  { id: 'tanglish', label: 'Tanglish' },
] as const;

function matchLang(scenarioLang: string, filter: string): boolean {
  if (filter === 'all') return true;
  const s = scenarioLang.toLowerCase();
  if (filter === 'english') return s === 'en' || s === 'english';
  if (filter === 'tamil') return s === 'ta' || s === 'tamil';
  if (filter === 'tanglish') return s === 'tanglish';
  return true;
}

function studioLang(scenarioLang: string): string {
  const s = scenarioLang.toLowerCase();
  if (s === 'ta' || s === 'tamil') return 'ta';
  if (s === 'tanglish') return 'tanglish';
  return 'en';
}

export default function ScenariosPage() {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [categories, setCategories] = useState<Record<string, number>>({});
  const [category, setCategory] = useState<string>('all');
  const [lang, setLang] = useState<(typeof LANG_FILTERS)[number]['id']>('all');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    void (async () => {
      setLoading(true);
      try {
        const data = await fetchScenarios(DEFAULT_TTS_SERVER);
        setScenarios(data.scenarios || []);
        setCategories(data.categories || {});
      } catch (e) {
        setError(String(e instanceof Error ? e.message : e));
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const filtered = useMemo(() => {
    return scenarios.filter((s) => {
      if (category !== 'all' && s.category !== category) return false;
      return matchLang(s.lang, lang);
    });
  }, [scenarios, category, lang]);

  return (
    <ShellFrame
      title="Scenarios"
      subtitle="Taxi contact-center use cases from the Movio acceptance suite — open any card in TTS Studio."
    >
      {error ? (
        <p className="mb-4 border border-[#f0c2bd] bg-[#fff5f4] px-3 py-2 text-sm text-[#b42318]">
          {error}
        </p>
      ) : null}

      <div className="mb-3 flex flex-wrap gap-1.5">
        <button
          type="button"
          onClick={() => setCategory('all')}
          className={cn(
            'border px-3 py-1.5 text-xs font-semibold',
            category === 'all'
              ? 'border-[#0a1628] bg-[#0a1628] text-white'
              : 'border-[#cfd8e0] bg-white text-[#5a6a7a] hover:border-[#0f6e6e]'
          )}
        >
          All ({scenarios.length})
        </button>
        {Object.entries(categories).map(([cat, count]) => (
          <button
            key={cat}
            type="button"
            onClick={() => setCategory(cat)}
            className={cn(
              'border px-3 py-1.5 text-xs font-semibold',
              category === cat
                ? 'border-[#0a1628] bg-[#0a1628] text-white'
                : 'border-[#cfd8e0] bg-white text-[#5a6a7a] hover:border-[#0f6e6e]'
            )}
          >
            {cat} ({count})
          </button>
        ))}
      </div>

      <div className="mb-4 flex flex-wrap gap-1.5">
        {LANG_FILTERS.map((f) => (
          <button
            key={f.id}
            type="button"
            onClick={() => setLang(f.id)}
            className={cn(
              'px-3 py-1 text-xs font-semibold uppercase tracking-[0.1em]',
              lang === f.id
                ? 'bg-[#0f6e6e] text-white'
                : 'bg-white text-[#5a6a7a] ring-1 ring-[#cfd8e0] hover:text-[#0a1628]'
            )}
          >
            {f.label}
          </button>
        ))}
      </div>

      {loading ? (
        <p className="text-sm text-[#5a6a7a]">Loading scenarios…</p>
      ) : (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {filtered.map((s) => {
            const href = `/studio?text=${encodeURIComponent(s.text)}&lang=${encodeURIComponent(studioLang(s.lang))}`;
            return (
              <article key={s.id} className="flex flex-col border border-[#cfd8e0] bg-white p-4">
                <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#0f6e6e]">
                  {s.category}
                </p>
                <h2 className="mt-1 font-[family-name:var(--font-display)] text-lg font-bold leading-snug">
                  {s.title}
                </h2>
                <p className="mt-1 text-xs text-[#5a6a7a]">{s.blurb}</p>
                <p className="mt-3 flex-1 text-sm leading-relaxed text-[#0a1628]">{s.text}</p>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {s.tags?.map((t) => (
                    <span
                      key={t}
                      className="border border-[#cfd8e0] bg-[#f7f9fb] px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-[#5a6a7a]"
                    >
                      {t}
                    </span>
                  ))}
                </div>
                <Link
                  href={href}
                  className="mt-4 inline-flex h-9 items-center justify-center bg-[#0a1628] px-3 text-sm font-semibold text-white hover:bg-[#0f6e6e]"
                >
                  Use in Studio
                </Link>
              </article>
            );
          })}
          {filtered.length === 0 ? (
            <p className="text-sm text-[#94a3b0]">No scenarios match these filters.</p>
          ) : null}
        </div>
      )}
    </ShellFrame>
  );
}
