# Clause + Template TTS Cache — Final Report

## Architecture changes

Extended the existing `AudioCache` and chunked TTS pipeline (no separate prototype).

Lookup hierarchy:

```text
Request
  → normalize (+ pronunciation lexicon)
  → full utterance cache?  HIT → return
  → split clauses
  → match taxi templates (phrase-sized units, not words)
  → cold template? synthesize whole clause once, warm static prefix
  → warm template? stitch cached static + new dynamic slot
  → in-flight coalescing per cache key
  → concat with short silence gap → store full utterance
```

## Files changed

| File | Change |
|------|--------|
| `server/cache.py` | Rich keys, layered metrics, in-flight coalescing |
| `server/pipeline.py` | Full → clause → template hierarchy |
| `server/templates.py` | Template registry matcher |
| `server/websocket_stream.py` | Stitch gaps, WAV/MP3 decode, stdlib fallback |
| `server/main.py` | Comment: layered cache still applies for fast backends |
| `config.py` | Template path + clause/template/gap settings |
| `normalization/taxi_templates.json` | Configurable taxi phrase/templates |
| `tests/test_cache_hierarchy.py` | Identity, slots, reuse, concurrency, stitch |
| `benchmark/run_cache_benchmark.py` | Before/after latency benchmark |
| `benchmark/run_phone_cache_sim.py` | Phone A↔B pipeline cache simulation |

## Cache hierarchy (actual flow)

1. **Full sentence** — SHA256(text ‖ lang ‖ voice ‖ pronunciation_version ‖ model ‖ format ‖ level=full)
2. **Clause** — same identity, `level=clause`, after `split_clauses`
3. **Template/slot** — phrase units from `taxi_templates.json`; dynamic slots always part of the key
4. **TTS** — only misses; concurrent identical keys share one generation

## Benchmark (measured)

Dataset: 29 taxi-domain sentences (ETA/OTP/location families + exact repeats).

Mock backend with length-scaled latency (isolates cache behaviour).

| Metric | BEFORE (full only) | AFTER (full+clause) | AFTER (full+clause+template) |
|--------|--------------------|---------------------|------------------------------|
| TTS calls | 27 | 26 | 36* |
| Avg e2e ms | ~89 | ~84 | ~75 |
| Cache hit rate | 0.036 | 0.086 | 0.25 |
| Template-family avg ms | ~105 | ~103 | ~70 |

\*Extra TTS calls are cold-path static **warm-ups** (not on the audible stitch for first utterance). Subsequent slot variants only synthesize the short dynamic unit → lower e2e.

Improvement vs before (full only):

- Clause path: **~6–7%** lower avg e2e
- Clause+template: **~15–16%** lower avg e2e (~14 ms on this mock)

Raw JSON: `benchmark/results/cache_hierarchy_benchmark.json`

## Cache hit examples

- Exact repeat `"Your driver has arrived."` → **full** hit (0 TTS)
- `"Your driver will arrive in 7 minutes."` after a prior ETA → static hit + dynamic miss (`units_from_cache=1`)
- Phone sim round 2 locations/OTPs → `template_hits` reuse of prefixes

## TTS calls saved

- Full+clause vs before: **1** call saved on this dataset (mostly unique utterances)
- Hits recorded on template path: **hit rate 0.25**, with static prefix reuse across ETA/OTP/location families
- Phone A↔B sim: **6 template hits**, `tts_calls_saved=6`, round2 avg e2e lower than round1

## Latency improvement

| Path | Measured |
|------|----------|
| Full-only → clause | ≈ 5–6 ms avg e2e (mock) |
| Full-only → clause+template | ≈ 14 ms avg e2e (mock), **~16%** |
| Phone sim round1 → round2 | ≈ 1.7 ms on mock SAPI (warm cache) |

Live `pywin32` was not available in this environment (SAPI mock). Re-run `python -m benchmark.run_phone_cache_sim` on the LOQ with SAPI/Edge for real phone numbers.

## Naturalness

- Cold templates synthesize the **whole clause** (no stitch) — same prosody as full TTS
- Warm templates stitch phrase-sized units (`Your driver will arrive` + `in seven minutes.`) with ~90 ms gap — **not** word-by-word
- Mock duration delta for cold path: **0.0 s** (single unit)
- Listen to `benchmark/results/cache_naturalness/*.wav` when real SAPI/Edge is available

## Test results

```text
Full cache: PASS
Clause cache: PASS
Template cache: PASS
Dynamic slots: PASS
Pronunciation compatibility: PASS (keys include pronunciation_version)
Concurrent deduplication: PASS
Audio stitching: PASS
Phone A → B: PASS (pipeline sim)
Phone B → A: PASS (pipeline sim)
Latency benchmark: PASS
```

`python -m unittest tests.test_cache_hierarchy tests.test_pipeline` → OK

## Final recommendation

**Use: Full sentence cache + Clause cache + Template cache**

Defaults (`CLAUSE_CACHE_ENABLED=true`, `TEMPLATE_CACHE_ENABLED=true`) match this.

Rationale from measurements: template path raised hit rate to **0.25** and cut average e2e by **~16%** vs full-only, despite more warm-up TTS calls. Phrase-sized units preserve naturalness better than word stitching; cold path avoids stitch degradation entirely.

If a deployment sees audible stitch artifacts on a specific template, remove or widen that template in `normalization/taxi_templates.json` — clause+full cache remain.
