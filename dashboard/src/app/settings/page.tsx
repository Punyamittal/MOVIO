'use client';

import { useEffect, useState } from 'react';
import { ShellFrame } from '@/components/section-frame';
import { DEFAULT_TTS_SERVER } from '@/lib/api';

export default function SettingsPage() {
  const [health, setHealth] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    void fetch(`${DEFAULT_TTS_SERVER}/health`)
      .then((r) => r.json())
      .then(setHealth)
      .catch(() => setHealth(null));
  }, []);

  return (
    <ShellFrame
      title="Settings"
      subtitle="Runtime defaults from the TTS server health endpoint."
    >
      <div className="border border-[#cfd8e0] bg-white px-5 py-5">
        <dl className="grid gap-3 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#5a6a7a]">
              API
            </dt>
            <dd className="mt-1 font-medium">{DEFAULT_TTS_SERVER}</dd>
          </div>
          <div>
            <dt className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#5a6a7a]">
              Default backend
            </dt>
            <dd className="mt-1 font-medium">
              {String(health?.default_backend ?? '—')}
            </dd>
          </div>
          <div>
            <dt className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#5a6a7a]">
              Device
            </dt>
            <dd className="mt-1 font-medium">{String(health?.tts_device ?? '—')}</dd>
          </div>
          <div>
            <dt className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#5a6a7a]">
              Loaded backends
            </dt>
            <dd className="mt-1 font-medium">
              {Array.isArray(health?.loaded_backends)
                ? (health?.loaded_backends as string[]).join(', ')
                : '—'}
            </dd>
          </div>
        </dl>
        <p className="mt-4 text-xs text-[#5a6a7a]">
          Change defaults in movio-indicvoice/.env (DEFAULT_TTS_BACKEND, SERVER_PORT, cache flags).
        </p>
      </div>
    </ShellFrame>
  );
}
