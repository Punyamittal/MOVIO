# Dataset Pipeline — Fine-tuning Data Collection

Separated speech/transcript dataset builder for Movio / IndicVoice.

Does **not** overwrite `sourcing/output`, `data_generation/output`, `benchmark/data`,
or runtime server state. All artifacts live under `dataset_pipeline/output/`.

This repo previously had **no audio shards / fine-tune scripts**. This pipeline
prepares verified data for a *future* fine-tune — it does **not** start training.

## Architecture

```text
Source Discovery (YouTube / user / existing corpora)
      ↓
Candidate Selection
      ↓
Permission / License Check   → usable_for_training true|false
      ↓
Media / Transcript Acquisition  (audio only if permitted; else metadata-only)
      ↓
Audio Extraction (16 kHz mono WAV — matches phone_test / Whisper)
      ↓
VAD Segmentation
      ↓
STT (phone_test IndicWhisper / Whisper)
      ↓
Language Detection (ta | en | ta-en | other | unknown)
      ↓
Normalization (deterministic_normalizer)
      ↓
Tanglish Generation (language_translator)  ← separate from EN translation
      ↓
Quality Validation (accepted | review | rejected)
      ↓
Deduplication (audio / text / near-dup / same segment)
      ↓
Speaker labeling (per-video contiguous)
      ↓
Train / Validation / Test   ← split by source_video (no clip leakage)
      ↓
Dataset Shards
```

Translation, Tanglish, and code-switching are stored as **separate fields**.

## Commands

From `movio-indicvoice/` (venv active):

```bash
pip install pyyaml
# optional:
# pip install yt-dlp

python -m dataset_pipeline discover --limit-queries 8
python -m dataset_pipeline collect --limit 10
python -m dataset_pipeline process
python -m dataset_pipeline verify --limit 20
python -m dataset_pipeline build
python -m dataset_pipeline stats
python -m dataset_pipeline baseline

# Or one shot (provisional splits until human verify):
python -m dataset_pipeline run-all --limit-queries 6 --limit-collect 10
```

## Config

| File | Purpose |
|------|---------|
| `config/dataset.yaml` | sample rates, split ratios, shard size, thresholds |
| `config/sources.yaml` | youtube / user_provided / existing_corpora adapters |
| `config/filtering.yaml` | accept / review / reject gates |
| `config/languages.yaml` | discovery query buckets |

## License policy

- **Never invent licenses.**
- Audio download only when `usable_for_training=true` (Creative Commons / public domain heuristics).
- Unclear YouTube sources → captions/metadata only, `usable_for_training=false`.
- Human verification required before final training shards.

## Output layout

```text
output/
  raw/candidates/     # discovery JSONL
  raw/media/          # permitted downloads
  clean/              # utterances.jsonl + audio clips
  verified/           # human-accepted + edits
  train|validation|test/
  shards/{split}/shard_XXX/{audio,metadata.jsonl,stats.json,verification.json}
  entities/           # OTP / locations / transport subset
  stats/              # report.json, report.md, charts
  baseline/           # fixed eval + baseline_report.json
  state/              # resumable progress + seen video ids
```

## Human review

```bash
python -m dataset_pipeline verify
```

Keys: **A** accept · **R** reject · **E** edit · **S** skip · **Q** quit  
Edits append to `verified/human_edits.jsonl` and are never overwritten by later `process`.

## User-provided authorized audio

Drop files into `output/raw/user_provided/` with optional sidecar `.json`:

```json
{
  "license": "user_authorized",
  "license_verified": true,
  "usable_for_training": true,
  "language": "ta-en",
  "domain": "transport"
}
```

Then `python -m dataset_pipeline collect`.
