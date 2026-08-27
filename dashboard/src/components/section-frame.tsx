'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { AppShell } from '@/components/app-shell';
import { DEFAULT_TTS_SERVER, fetchOverview, type OverviewResponse } from '@/lib/api';

export function ShellFrame({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string;
  children: React.ReactNode;
}) {
  const [overview, setOverview] = useState<OverviewResponse | null>(null);

  useEffect(() => {
    void fetchOverview(DEFAULT_TTS_SERVER)
      .then(setOverview)
      .catch(() => setOverview(null));
  }, []);

  return (
    <AppShell
      online={Boolean(overview?.status.engine_online)}
      statusLabel={overview?.status.label || 'Engine status'}
      statusDetail={overview?.status.detail || 'Connect TTS runtime on :8001'}
      version={overview?.version}
    >
      <div className="mb-6">
        <h1 className="font-[family-name:var(--font-display)] text-3xl font-extrabold tracking-tight">
          {title}
        </h1>
        <p className="mt-2 max-w-2xl text-sm text-[#5a6a7a]">{subtitle}</p>
      </div>
      {children}
    </AppShell>
  );
}

export function ComingSoon({
  title,
  subtitle,
  href = '/studio',
  cta = 'Open TTS Studio',
}: {
  title: string;
  subtitle: string;
  href?: string;
  cta?: string;
}) {
  return (
    <ShellFrame title={title} subtitle={subtitle}>
      <div className="border border-[#cfd8e0] bg-white px-5 py-8">
        <p className="text-sm text-[#5a6a7a]">
          This panel is wired into the platform shell. Core synthesis still runs through Studio so
          existing flows stay intact.
        </p>
        <Link
          href={href}
          className="mt-4 inline-flex h-10 items-center bg-[#0a1628] px-4 text-sm font-semibold text-white hover:bg-[#0f6e6e]"
        >
          {cta}
        </Link>
      </div>
    </ShellFrame>
  );
}
