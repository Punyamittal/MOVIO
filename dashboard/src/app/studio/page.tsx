'use client';

import { Suspense } from 'react';
import StudioWorkspace from '@/components/studio-workspace';

export default function StudioRoute() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-screen items-center justify-center bg-[#edf1f4] text-sm text-[#5a6a7a]">
          Loading studio…
        </div>
      }
    >
      <StudioWorkspace />
    </Suspense>
  );
}
