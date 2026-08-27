'use client';

import { useEffect, useState } from 'react';
import { ExternalLink, RefreshCw } from 'lucide-react';
import { ShellFrame } from '@/components/section-frame';
import { DEFAULT_TTS_SERVER } from '@/lib/api';

export default function TwoPhoneTestPage() {
  const base = DEFAULT_TTS_SERVER.replace(/\/$/, '');
  const embedSrc = `${base}/test/?embed=1`;
  const fullSrc = `${base}/test/`;
  const [frameKey, setFrameKey] = useState(0);
  const [reachable, setReachable] = useState<boolean | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${base}/test/api/lan`, { cache: 'no-store' });
        if (!cancelled) setReachable(res.ok);
      } catch {
        if (!cancelled) setReachable(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [base, frameKey]);

  return (
    <ShellFrame
      title="Two-Phone Test"
      subtitle="Scan QR codes with two phones on the same Wi-Fi — STT → translate → TTS through this laptop."
    >
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <a
          href={fullSrc}
          target="_blank"
          rel="noreferrer"
          className="inline-flex h-10 items-center gap-2 border border-[#cfd8e0] bg-white px-3 text-sm font-semibold text-[#0a1628] transition hover:border-[#0f6e6e]"
        >
          <ExternalLink className="h-3.5 w-3.5" />
          Open full panel
        </a>
        <button
          type="button"
          onClick={() => setFrameKey((k) => k + 1)}
          className="inline-flex h-10 items-center gap-2 border border-[#cfd8e0] bg-white px-3 text-sm font-medium text-[#0a1628] transition hover:border-[#0f6e6e]"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          Reload
        </button>
        <span className="text-xs text-[#5a6a7a]">
          {reachable === null
            ? 'Checking…'
            : reachable
              ? `Live at ${fullSrc}`
              : 'Phone-test API not reachable — start movio-indicvoice on :8001'}
        </span>
      </div>

      {reachable === false ? (
        <div className="border border-[#f0c2bd] bg-[#fff5f4] px-4 py-4 text-sm text-[#b42318]">
          <p className="font-semibold">Two-phone environment is offline</p>
          <p className="mt-2 text-[#0a1628]">
            In a terminal:
          </p>
          <pre className="mt-2 overflow-x-auto bg-[#0a1628] px-3 py-2 text-xs text-white">
{`cd movio-indicvoice
.venv\\Scripts\\activate
python -m server.main`}
          </pre>
          <p className="mt-2 text-xs text-[#5a6a7a]">
            Then open <code className="text-[#0a1628]">{fullSrc}</code> or reload this page.
          </p>
        </div>
      ) : (
        <div className="overflow-hidden border border-[#cfd8e0] bg-white">
          <iframe
            key={frameKey}
            title="Two-phone local test"
            src={embedSrc}
            className="h-[78vh] w-full"
          />
        </div>
      )}

      <p className="mt-3 text-xs leading-relaxed text-[#5a6a7a]">
        Phones must use the <strong className="font-semibold text-[#0a1628]">LAN IP</strong> shown in
        the panel (not localhost). Same Wi-Fi as this laptop. Direct URL:{' '}
        <a className="font-medium text-[#0f6e6e] underline-offset-2 hover:underline" href={fullSrc} target="_blank" rel="noreferrer">
          {fullSrc}
        </a>
      </p>
    </ShellFrame>
  );
}
