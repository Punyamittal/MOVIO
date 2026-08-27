# Bug-hunting utterance pack

Source: `benchmark/data/bug_hunting_sentences.json` (64 sentences).

## Categories

| Category | Count | What it stresses |
|----------|------:|------------------|
| conversational | 8 | conjunctions, mixed intent |
| long | 5 | multi-clause / long TTS |
| numbers_otp | 8 | OTP, currency, times, IDs |
| names_places | 7 | lexicon / Chennai places |
| questions | 9 | interrogives |
| confusable | 8 | STT lookalikes (fifteen/fifty) |
| spoken | 10 | informal contractions |
| translation_stress | 8 | contrast / mixed tenses |
| bug_hunting_e2e | 1 | kitchen-sink long line |

## How we use them

```bash
python -m benchmark.run_bug_hunt_benchmark
python -m benchmark.run_phone_cache_sim
```

Results: `benchmark/results/bug_hunt_benchmark.json`, `phone_cache_sim.json`.

## Measured takeaway (mock TTS)

- **Pass 1 (unique cold):** full-only can beat clause/template on long unique speech (splitting → more sequential synths).
- **Pass 2 (exact replay):** full-utterance cache hit rate **1.0**, ~**1.8 ms** e2e.
- Layered cache shines on **repeats / template families**; bug-hunt lines prove normalization (OTP digits, places) and long-audio chunking still work.
