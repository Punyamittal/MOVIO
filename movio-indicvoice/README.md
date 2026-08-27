# movio-indicvoice

Self-hosted, low-latency **Tamil–English–Tanglish** TTS for a taxi voice-agent.

Built in **four independently runnable phases**. Phase N’s runtime path may use Phase N−1 artifacts, but each phase has its own entrypoints and can be tested before the next is layered on. **No model training or fine-tuning** — prompt-based / off-the-shelf only. Comments mark where a future QLoRA step could be inserted; it is not implemented.

**TTFA target:** ~100 ms on the **edge_fast** path (default). Fine-tuning is **not** used — it does not reduce latency; this stack is prompt / off-the-shelf only. · **Concurrency target:** 15–20 (measure and report honest ceiling on your hardware)

---

## Setup

```bash
cd movio-indicvoice
python -m venv .venv

# Windows
.venv\Scripts\activate
# Linux/macOS
# source .venv/bin/activate

pip install -r requirements.txt
# On some Linux/PEP-668 systems:
#   pip install --break-system-packages -r requirements.txt

# CRITICAL for <500ms-class TTFA: install CUDA PyTorch (Windows pip defaults to CPU).
# Your machine has an NVIDIA GPU but `pip install torch` often installs `+cpu`.
# RTX 40-series example (CUDA 12.6 wheels):
pip uninstall -y torch
pip install torch --index-url https://download.pytorch.org/whl/cu126
# Confirm: python -c "import torch; print(torch.cuda.is_available(), torch.__version__)"
# Expect: True 2.x.x+cu126

# Optional local TTS (IndicF5) — gated HF model
pip install git+https://github.com/ai4bharat/IndicF5.git

# Ollama LLM (local, no API key)
# Install Ollama, then:
ollama pull gemma4:31b
# Drop-in alternative (same env var) — often more reliable under RAM pressure:
#   ollama pull gemma4:26b
#   set OLLAMA_MODEL=gemma4:26b
# For faster local generation on a laptop, `gemma4:latest` also works via OLLAMA_MODEL.

# Hugging Face gated model (IndicF5) — optional quality path
# Without access the F5 backend uses silent mock WAV; edge_fast still works online.
# 1. Create a HF account and request access:
#      https://huggingface.co/ai4bharat/IndicF5
# 2. Then in the venv:
#      pip install huggingface_hub
#      huggingface-cli login
# 3. Restart: python -m server.main
# First successful download can take several minutes — raise QUEUE_REQUEST_TIMEOUT_SEC
# (e.g. 600) for the first load if needed.

copy .env.example .env   # Windows
# cp .env.example .env   # Linux/macOS
```

**Server port:** default is **8001** (config / `.env`). Port 8000 is often taken by other local tools on Windows.

Python **3.10+** required.

---

## Phase-by-phase run order

### PHASE 1 — Core pipeline

Must work correctly before later phases matter. Downstream code **never** depends on `sourcing/output/` existing; if sourcing is skipped, use `benchmark/data/offline_sentences.json` (checked in, offline).

```bash
# Optional sourcing (non-blocking; safe to skip)
python sourcing/youtube_transcripts.py      # local only — cloud IPs often blocked
python sourcing/hf_datasets_loader.py       # tamilmixsentiment sample
python sourcing/extract_patterns.py

# Synthetic data (needs Ollama)
python data_generation/generate.py
python data_generation/review.py            # keep/edit/delete/quit CLI

# Fill pronunciation placeholders
#   edit normalization/pronunciation_lexicon.json
# optional merge docs:
python normalization/lexicon_builder.py

# Unit tests (normalizers + smoke pipeline; TTS may mock if weights missing)
python -m tests.test_pipeline

# Manual E2E server (Phase 1 style: set QUEUE_ENABLED=false for direct path)
# In .env: QUEUE_ENABLED=false
python -m server.main
# POST http://127.0.0.1:8000/tts
# {"text":"Your OTP is 4821","return_audio_base64":true,"skip_llm":true}
```

Pipeline order: **language translator → deterministic normalizer → lexicon → Tanglish LLM (optional) → validator → TTS (default Edge fast)**.

Speak-as targets: `tanglish` (default) · `en` · `ta` · `auto`. Engines: offline taxi lexicon → Ollama → Google (when reachable).

### PHASE 2 — Latency, streaming, cache, optimization

```bash
python optimization/quantize.py
python optimization/compile_model.py
# Pick precision / compile settings in config or env, then:
python benchmark/run_benchmark.py
# Inspect TTFA vs full-synthesis (always separate) in benchmark/results/summary.json

# Server with cache (CACHE_ENABLED=true) + WS streaming
python -m server.main
# WS: ws://127.0.0.1:8000/tts/stream
# Verify cache: repeat the same phrase and check /health cache hit_rate
```

Chunked WS streaming is **pipelined clause/sentence streaming**, not token-level audio streaming (see comment in `server/websocket_stream.py`).

### PHASE 3 — Concurrency & queue

```bash
# .env: QUEUE_ENABLED=true  (default)
python -m server.main

# Separate terminal:
python concurrency/load_test.py
# resource_monitor is used inside load_test; standalone:
python concurrency/resource_monitor.py

# Review:
#   concurrency/results/latency_vs_concurrency.json
#   concurrency/results/concurrency_report.md
```

If a laptop GPU cannot sustain 15–20 concurrent requests, the **measured ceiling is reported honestly** — results are never faked or omitted.

### PHASE 4 — Evaluation, cost, demo, report

```bash
python evaluation/asr_wer_cer.py
# Fill evaluation/mos_scoring_template.csv manually (human MOS)
python evaluation/movio_acceptance.py

# Set HARDWARE_COST_PER_HOUR in .env to your real target ($/hour), then:
python cost_analysis/cost_calculator.py

python report/generate_report.py
# Edit [FILL IN: your analysis here] sections in report/FINAL_REPORT.md

# Demo (server must be running)
# Open demo/dashboard.html in a browser
```

---

## Design principle (normalization)

Natural **spoken Tanglish**, not literary Tamil translation. Terms in `normalization/preserve_english_list.json` stay Latin-script inline:

- Good: `உங்க driver 5 minutes ல வந்துருவாங்க`
- Bad: full Tamil-script literary paraphrase of every loanword

See the comment block at the top of `normalization/tanglish_llm_layer.py`.

---

## Licensing notes

| Asset | License / note |
|-------|----------------|
| Edge neural voices (edge-tts) | Microsoft Edge read-aloud service terms |
| IndicF5 | MIT |
| MMS Tamil | **Excluded** (CC-BY-NC-4.0) — incompatible with Movio as a commercial acquisition target |
| Reddit sourcing | **Excluded** — 2026 API closure / new-developer denial |
| YouTube / HF sourced text | Internal reference only; does not block core pipeline |

---

## Known limitations

- **No fine-tuning** performed. QLoRA is a documented future step only, triggered if benchmarks show consistent Tanglish error classes (see `validator_flags.log` and comments in `tanglish_llm_layer.py`).
- **Local hardware ≠ production hardware** — report measured concurrency ceiling honestly.
- **WER/CER noise** on code-mixed Tanglish audio (ASR also struggles); dual references (raw vs normalized) are required for fair reading.
- Optional sourcing may fail (YouTube blocks, HF offline) without affecting the core path.

---

# Two-Phone Local Testing

End-to-end test mode where **two real phones** join a session via QR codes and talk through this laptop. The laptop runs the existing STT → translate → TTS pipeline (not a fake demo).

```text
              LAPTOP (movio-indicvoice)
        Local Translation Server :8001
                 │
       ┌─────────┴─────────┐
   Session A            Session B
   QR Code A             QR Code B
       │                   │
   PHONE A              PHONE B
   Mic/Speaker          Mic/Speaker
```

## Requirements

- Same Wi-Fi for laptop + both phones (phones cannot use `localhost`)
- Python venv with `requirements.txt` installed (includes `openai-whisper`)
- Working TTS backend (default `win_sapi` / `edge_fast` is fine for latency testing)
- Optional: OpenSSL if you need `--https` for Chrome microphone on LAN HTTP

## Installation

Same as main setup (`pip install -r requirements.txt`). No extra packages required for QR (generated in the browser).

## Startup command

```bash
cd movio-indicvoice
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/macOS

python -m phone_test
```

Useful flags:

```bash
python -m phone_test --https          # self-signed TLS (Chrome mic on LAN)
python -m phone_test --no-browser     # do not auto-open dashboard
python -m phone_test --port 8001
```

Startup prints LAN URLs. Open the laptop dashboard at `http://localhost:8001/test/` (or the HTTPS equivalent).

## Wi-Fi requirements

Both phones must reach the laptop LAN IP (e.g. `http://192.168.1.10:8001`). If the page does not load, allow inbound TCP on the server port in Windows Firewall.

## How to use

1. Start `python -m phone_test` on the laptop.
2. On the dashboard, pick the correct LAN address if multiple interfaces are listed.
3. **Phone A**: scan QR Code A → browser opens Phone A client.
4. **Phone B**: scan QR Code B → browser opens Phone B client.
5. Tap **Enable microphone / audio** on each phone; allow mic permission.
6. Set languages (defaults: A speaks Tamil/Tanglish → B hears English; reverse on B).
7. Hold **HOLD TO SPEAK**, talk, release. Partner hears translated TTS.
8. Watch the laptop dashboard for transcripts, translations, latency, and debug logs.

## Architecture

```text
PHONE A mic (WAV over WebSocket)
   → laptop STT (evaluation ASR: IndicWhisper or openai-whisper)
   → existing language_translator + normalizer + TTSPipeline
   → TTS audio over WebSocket
   → PHONE B speaker
```

Reverse path is symmetric. Transport is WebSocket (push-to-talk utterances), reusing `server.main._run_tts` — no duplicated translation/TTS logic.

## Automated self-test (no phones)

With the server already running:

```bash
python -m phone_test.simulate
# or from a second terminal while server runs:
python -m phone_test --simulate-only
```

This checks session create + A→B / B→A text → translate → TTS. Mic STT still needs real phones (or browsers).

Manual checklist: `phone_test/CHECKLIST.md`.

## Troubleshooting

| Symptom | Fix |
|--------|-----|
| Phones cannot open URL | Same Wi-Fi; use LAN IP not localhost; check firewall |
| Mic blocked on Chrome | `python -m phone_test --https` and accept cert warning, or use Firefox |
| Empty STT | Speak closer; check `/test/api/stt-status`; wait for Whisper load |
| No speech on partner | Confirm both Connected; check dashboard debug log |
| Invalid / expired session | Click **New session** and rescan both QR codes |

## Known limitations (phone-test)

- **Push-to-talk only** by default (no automatic VAD in v1 — keeps debugging reliable).
- STT is **utterance-based**, not streaming token ASR — end-to-end latency includes full hold duration + Whisper + TTS.
- Chrome may require HTTPS or an insecure-origin flag for `getUserMedia` on LAN HTTP.
- Evaluation ASR (Whisper) is reused — Tanglish WER can be noisy (same limitation as offline eval).
- Not a production calling stack (no WebRTC media path; local test only).

---

## Project layout

See repository tree: `sourcing/`, `data_generation/`, `normalization/`, `tts_backends/`, `server/`, `phone_test/`, `optimization/`, `benchmark/`, `concurrency/`, `evaluation/`, `cost_analysis/`, `demo/`, `report/`, `tests/`.

Config hub: `config.py` + `.env`.
