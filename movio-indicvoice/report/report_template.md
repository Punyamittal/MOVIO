# movio-indicvoice — Technical Report

## Background & Objective

[FILL IN: your analysis here]

## Architecture Overview

[FILL IN: your analysis here]

Pipeline order: deterministic normalizer → pronunciation lexicon → Tanglish LLM layer → validator → TTS backend (default edge_fast).

## Model Selection & Rationale

| Component | Choice | License | Role |
|-----------|--------|---------|------|
| Primary TTS | edge-tts (Edge neural) | Edge service terms | Low-latency production path |
| Comparison TTS | ai4bharat/IndicF5 | MIT | Optional local A/B |
| LLM normalizer | Ollama Gemma 4 (`OLLAMA_MODEL`) | per Ollama/model terms | Prompt-only Tanglish |
| MMS Tamil | **Excluded** | CC-BY-NC-4.0 | Commercial incompatibility |

[FILL IN: your analysis here]

## Text Normalization Approach

Design principle: **natural spoken Tanglish**, not literary Tamil translation. English loanwords in `preserve_english_list.json` stay Latin-script inline.

[FILL IN: your analysis here]

## TTFA & Latency Results

> TTFA and full-synthesis latency are reported separately — never collapsed.

<!-- AUTO:BENCHMARK_TABLE -->

[FILL IN: your analysis here]

## Optimization Results

### Quantization

<!-- AUTO:QUANTIZATION_TABLE -->

### Compilation (`torch.compile`)

<!-- AUTO:COMPILATION_TABLE -->

[FILL IN: your analysis here]

## Concurrency Results

<!-- AUTO:CONCURRENCY_TABLE -->

### Hardware ceiling (honest)

<!-- AUTO:CONCURRENCY_CEILING -->

[FILL IN: your analysis here]

## Cost Analysis

<!-- AUTO:COST_TABLE -->

Hardware $/hour used: <!-- AUTO:COST_PER_HOUR -->

[FILL IN: your analysis here]

## Quality Evaluation

### WER / CER (dual reference)

<!-- AUTO:WER_CER_TABLE -->

Known limitation: WER/CER is noisier for Tanglish because ASR also struggles with code-mixed audio.

### MOS

Fill `evaluation/mos_scoring_template.csv` manually, then summarize here.

[FILL IN: your analysis here]

### Acceptance tests

<!-- AUTO:ACCEPTANCE_SUMMARY -->

[FILL IN: your analysis here]

## Limitations

- No fine-tuning / QLoRA performed (documented future step only).
- Local laptop GPU results may not transfer to production hardware.
- WER/CER noise on code-mixed audio.
- Optional sourcing (YouTube / HF) must never block the core pipeline.

[FILL IN: your analysis here]

## Production Readiness Recommendation

[FILL IN: your analysis here]
