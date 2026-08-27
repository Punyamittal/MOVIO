import { ShellFrame } from '@/components/section-frame';

export default function Page() {
  return (
    <ShellFrame
      title="Architecture"
      subtitle="System design for the self-hosted Movio Indic voice stack."
    >
      <div className="border border-[#cfd8e0] bg-white px-5 py-6 text-sm leading-relaxed text-[#5a6a7a]">
        <ol className="list-decimal space-y-2 pl-5 text-[#0a1628]">
          <li>Client (Next dashboard / demo HTML / phone WebSocket)</li>
          <li>FastAPI server — translate → normalize → lexicon → TTS</li>
          <li>Backends: win_sapi (local), edge_fast (neural cloud), optional local models</li>
          <li>Cache + telemetry feed the Overview KPIs</li>
          <li>Evaluation artifacts: acceptance, WER/CER, MOS template, benchmarks</li>
        </ol>
      </div>
    </ShellFrame>
  );
}
