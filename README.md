![Project Banner](docs/readme-agent/banner.svg)

## Setup Guide

### Backend Setup

_From `movio-indicvoice/README.md`:_


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

### Frontend Setup (Dashboard)

```bash
cd dashboard
npm install
npm run dev     # development
npm run build && npm start   # production
```

Open `http://localhost:3000` (or the port shown in the terminal).

### Configuration

Copy environment templates before running:

- `movio-indicvoice/.env.example` → copy to `.env` in the same directory

Dashboard connects to the TTS server via `NEXT_PUBLIC_TTS_SERVER` (default `http://127.0.0.1:8001`).

### Running the Application

1. **Start the backend** (TTS server on port `8001`)
2. **Start the dashboard** (`npm run dev` in `dashboard/`)
3. Open the dashboard and verify engine status shows **online**

```bash
# Terminal 1 — Backend
cd movio-indicvoice && python -m server.main

# Terminal 2 — Frontend
cd dashboard && npm run dev
```

## System Architecture

High-level system design, data flows, API map, and workflow pipelines derived from the repository structure.

### System Architecture

```mermaid
graph TB
    subgraph Client["Client Layer"]
        user["User / Operator"]
    end

    subgraph Frontend["dashboard/ — Next.js + React + TypeScript"]
        pages["App Router Pages<br/>Studio · Benchmark · Evaluation · Settings"]
        components["UI Components<br/>Charts · KPI Cards · Shell Layout"]
        lib["API Client lib/<br/>fetchOverview · studio · normalize"]
    end

    subgraph Backend["movio-indicvoice/ — Python TTS Runtime"]
        api["FastAPI Server<br/>server/ · port 8001"]
        benchmark["benchmark/"]
        concurrency["concurrency/"]
        cost_analysis["cost_analysis/"]
        data_generation["data_generation/"]
        benchmark --> concurrency --> cost_analysis --> data_generation
        demo["demo/"]
        evaluation["evaluation/"]
        normalization["normalization/"]
        optimization["optimization/"]
        demo --> evaluation --> normalization --> optimization
        phone_test["phone_test/"]
        reference_voices["reference_voices/"]
        report["report/"]
        scripts["scripts/"]
        phone_test --> reference_voices --> report --> scripts
    end

    subgraph Data["Data & Artifacts"]
        bench_data["benchmark/data/<br/>JSON sentence corpora"]
        bench_results["benchmark/results/<br/>summary.json · metrics"]
        env_cfg[".env.example · config.py"]
    end

    subgraph Charts["Dashboard Chart Feeds"]
        activity_7d["7-day activity chart"]
        language_mix["Language mix chart"]
        voice_usage["Voice usage chart"]
        ttfa_distribution["TTFA distribution"]
        trend_by_voice["Voice trend chart"]
        trend_by_lang["Language trend chart"]
    end

    user --> pages
    pages --> components
    components --> lib
    lib -->|REST JSON| api
    api --> bench_data
    api --> bench_results
    api --> benchmark & concurrency & cost_analysis & data_generation
    api -->|/dashboard/overview| Charts
    components --> Charts
```

### Data Flow & Charts Pipeline

```mermaid
flowchart LR
    U["User"] --> UI["Dashboard UI"]
    UI --> API["TTS Server API<br/>:8001"]

    subgraph Ingest["Input Pipeline"]
        text["Text / Scenario Input"]
        norm["Normalizer Rules"]
        synth["TTS Synthesis"]
    end

    subgraph Metrics["Metrics Collection"]
        ttfa["TTFA ms"]
        p99["p99 Latency"]
        wer["WER / MOS"]
        cost["Cost Analysis"]
    end

    subgraph Viz["Dashboard Charts"]
        activity_7d["7-day activity chart"]
        language_mix["Language mix chart"]
        voice_usage["Voice usage chart"]
        ttfa_distribution["TTFA distribution"]
        trend_by_voice["Voice trend chart"]
        trend_by_lang["Language trend chart"]
        heatmap["Usage heatmap"]
        funnel["Studio funnel chart"]
    end

    UI --> text
    text --> norm
    norm --> synth
    synth --> API
    API --> ttfa
    API --> p99
    API --> wer
    API --> cost
    ttfa --> activity_7d
    p99 --> ttfa_distribution
    wer --> evaluation
    cost --> funnel
    API -->|/dashboard/overview| Viz
    Viz --> UI
```

### Component & API Map

```mermaid
graph LR
    subgraph Dashboard["Dashboard Pages"]
        home["/ — Overview KPIs"]
        studio["/studio — TTS Studio"]
        bench["/benchmark — Latency"]
        eval["/evaluation — Quality"]
    end

    subgraph API["Verified API Endpoints"]
        ep0["/dashboard/overview<br/>KPIs + charts bundle"]
        ep1["/studio/voices<br/>Voice catalog"]
        ep2["/studio/normalize<br/>Text normalization"]
        ep3["/tts<br/>Speech synthesis"]
        ep4["/studio/scenarios<br/>Scenario packs"]
    end

    home --> ep0
    studio --> ep1
    studio --> ep2
    studio --> ep3
    studio --> ep4
    bench --> ep0
    eval --> ep0
```

### Benchmark Workflow Pipeline

```mermaid
flowchart TB
    subgraph Input["Benchmark Inputs"]
        offline["offline_sentences.json"]
        taxi["taxi_driver_sentences.json"]
        tanglish["tanglish_gold_pairs.json"]
    end

    subgraph Runners["Benchmark Runners"]
        r0["benchmark"]
        r1["bug_hunt_benchmark"]
        r2["cache_benchmark"]
        r3["phone_cache_sim"]
        r4["translation_benchmark"]
    end

    subgraph Output["Results & Charts"]
        summary["summary.json"]
        metrics["metrics.py aggregates"]
        compare["Backend comparison table"]
        chart_p99["p99 TTFA chart"]
        chart_cost["Cost chart"]
    end

    offline --> r0
    taxi --> r0
    tanglish --> r0
    r0 --> summary
    summary --> metrics
    metrics --> compare
    compare --> chart_p99
    compare --> chart_cost
    chart_p99 --> dash["Dashboard /benchmark page"]
```

### Dashboard Page Map

```mermaid
mindmap
  root((MOVIO Dashboard))
    Overview
      home
    Build
      studio
      normalizer
      batch
      comparison
      pronunciation
      scenarios
    Evaluate
      phones
      agent
      benchmark
      evaluation
      architecture
    System
      settings
      demo
```
