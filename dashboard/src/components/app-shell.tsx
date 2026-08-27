'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  Activity,
  AudioLines,
  BarChart3,
  Boxes,
  FlaskConical,
  Gauge,
  LayoutDashboard,
  Mic2,
  Network,
  Settings,
  Sparkles,
  TextQuote,
  Layers3,
  GitCompare,
  BookOpen,
  Search,
  Smartphone,
} from 'lucide-react';
import { cn } from '@/lib/utils';

const NAV = [
  {
    section: 'Overview',
    items: [{ href: '/', label: 'Dashboard', hint: 'Live KPIs & overview', icon: LayoutDashboard }],
  },
  {
    section: 'Build',
    items: [
      { href: '/studio', label: 'TTS Studio', hint: 'Generate speech', icon: AudioLines },
      { href: '/normalizer', label: 'Text Normalizer', hint: 'Context-aware rules', icon: TextQuote },
      { href: '/batch', label: 'Batch Synthesis', hint: 'Bulk generation', icon: Layers3 },
      { href: '/comparison', label: 'Comparison Lab', hint: 'A/B voice testing', icon: GitCompare },
      { href: '/pronunciation', label: 'Pronunciation', hint: 'Custom overrides', icon: BookOpen },
      { href: '/scenarios', label: 'Scenarios', hint: 'Taxi use cases', icon: Sparkles },
    ],
  },
  {
    section: 'Evaluate',
    items: [
      { href: '/phones', label: 'Two-Phone Test', hint: 'QR pairing · local', icon: Smartphone },
      { href: '/agent', label: 'Live Voice Agent', hint: 'Real-time demo', icon: Mic2 },
      { href: '/benchmark', label: 'Benchmark', hint: 'Latency & cost', icon: Gauge },
      { href: '/evaluation', label: 'Evaluation', hint: 'Quality metrics', icon: FlaskConical },
      { href: '/architecture', label: 'Architecture', hint: 'System design', icon: Network },
    ],
  },
  {
    section: 'System',
    items: [{ href: '/settings', label: 'Settings', hint: 'Defaults & config', icon: Settings }],
  },
] as const;

type AppShellProps = {
  children: React.ReactNode;
  statusLabel?: string;
  statusDetail?: string;
  online?: boolean;
  version?: string;
};

export function AppShell({
  children,
  statusLabel = 'Engine status',
  statusDetail = 'Connect TTS runtime',
  online = false,
  version = 'v1.1 prototype',
}: AppShellProps) {
  const pathname = usePathname();

  return (
    <div className="flex min-h-screen bg-[#edf1f4] text-[#0a1628]">
      <aside className="sticky top-0 flex h-screen w-[16.5rem] shrink-0 flex-col border-r border-[#cfd8e0] bg-[#f7f9fb]">
        <div className="border-b border-[#cfd8e0] px-5 py-5">
          <Link href="/" className="block">
            <div className="font-[family-name:var(--font-display)] text-2xl font-extrabold tracking-tight">
              Movio
            </div>
            <p className="mt-0.5 text-xs font-medium text-[#5a6a7a]">Voice TTS Platform</p>
          </Link>
        </div>

        <nav className="flex-1 overflow-y-auto px-3 py-4">
          {NAV.map((group) => (
            <div key={group.section} className="mb-5">
              <p className="mb-2 px-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-[#94a3b0]">
                {group.section}
              </p>
              <ul className="space-y-0.5">
                {group.items.map((item) => {
                  const active =
                    item.href === '/'
                      ? pathname === '/'
                      : pathname === item.href || pathname.startsWith(`${item.href}/`);
                  const Icon = item.icon;
                  return (
                    <li key={item.href}>
                      <Link
                        href={item.href}
                        className={cn(
                          'flex items-start gap-2.5 rounded-md px-2.5 py-2 transition',
                          active
                            ? 'bg-[#0a1628] text-white'
                            : 'text-[#0a1628] hover:bg-white'
                        )}
                      >
                        <Icon
                          className={cn(
                            'mt-0.5 h-4 w-4 shrink-0',
                            active ? 'text-[#7dd3d3]' : 'text-[#0f6e6e]'
                          )}
                        />
                        <span className="min-w-0">
                          <span className="block text-sm font-semibold leading-tight">
                            {item.label}
                          </span>
                          <span
                            className={cn(
                              'block text-[11px] leading-snug',
                              active ? 'text-white/65' : 'text-[#5a6a7a]'
                            )}
                          >
                            {item.hint}
                          </span>
                        </span>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </nav>

        <div className="border-t border-[#cfd8e0] p-4">
          <div className="rounded-md border border-[#cfd8e0] bg-white px-3 py-3">
            <div className="flex items-center gap-2">
              <span
                className={cn(
                  'h-2 w-2 rounded-full',
                  online ? 'bg-[#0f6e6e]' : 'bg-[#b42318]'
                )}
              />
              <p className="text-sm font-semibold">{statusLabel}</p>
            </div>
            <p className="mt-1 text-[11px] leading-relaxed text-[#5a6a7a]">{statusDetail}</p>
          </div>
          <div className="mt-3 flex items-center justify-between px-1 text-[11px] text-[#94a3b0]">
            <span className="inline-flex items-center gap-1">
              <Search className="h-3 w-3" /> Search…
            </span>
            <span>{version}</span>
          </div>
        </div>
      </aside>

      <div className="min-w-0 flex-1">
        <header className="sticky top-0 z-10 flex items-center justify-between border-b border-[#cfd8e0] bg-[#edf1f4]/90 px-6 py-3 backdrop-blur">
          <div className="flex items-center gap-2 text-sm text-[#5a6a7a]">
            <Activity className="h-4 w-4 text-[#0f6e6e]" />
            <span className={online ? 'font-medium text-[#0f6e6e]' : 'font-medium text-[#b42318]'}>
              {online ? 'Engine online' : 'Engine offline'}
            </span>
            <span className="text-[#cfd8e0]">·</span>
            <span>v1.1</span>
          </div>
          <div className="inline-flex items-center gap-2 text-xs text-[#5a6a7a]">
            <BarChart3 className="h-3.5 w-3.5" />
            <span>Live KPIs</span>
            <Boxes className="h-3.5 w-3.5" />
          </div>
        </header>
        <main className="px-6 py-6">{children}</main>
      </div>
    </div>
  );
}
