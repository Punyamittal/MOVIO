"""
movio-indicvoice configuration.

All models, paths, ports, cost assumptions, concurrency levels, and cache settings.
Swap OLLAMA_MODEL via env — gemma4:31b (default) or gemma4:26b as drop-in alternative.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent
SOURCING_OUTPUT_DIR = PROJECT_ROOT / "sourcing" / "output"
DATA_GEN_OUTPUT_DIR = PROJECT_ROOT / "data_generation" / "output"
BENCHMARK_DATA_DIR = PROJECT_ROOT / "benchmark" / "data"
BENCHMARK_RESULTS_DIR = PROJECT_ROOT / "benchmark" / "results"
OPTIMIZATION_RESULTS_DIR = PROJECT_ROOT / "optimization" / "results"
CONCURRENCY_RESULTS_DIR = PROJECT_ROOT / "concurrency" / "results"
EVALUATION_RESULTS_DIR = PROJECT_ROOT / "evaluation" / "results"
COST_RESULTS_DIR = PROJECT_ROOT / "cost_analysis" / "results"
REPORT_DIR = PROJECT_ROOT / "report"
REFERENCE_VOICES_DIR = PROJECT_ROOT / "reference_voices"
NORMALIZATION_DIR = PROJECT_ROOT / "normalization"
DATASET_PIPELINE_DIR = PROJECT_ROOT / "dataset_pipeline"
DATASET_PIPELINE_OUTPUT_DIR = DATASET_PIPELINE_DIR / "output"

PRESERVE_ENGLISH_LIST_PATH = NORMALIZATION_DIR / "preserve_english_list.json"
PRONUNCIATION_LEXICON_PATH = NORMALIZATION_DIR / "pronunciation_lexicon.json"
TAXI_TEMPLATES_PATH = NORMALIZATION_DIR / "taxi_templates.json"
VALIDATOR_FLAGS_LOG = NORMALIZATION_DIR / "validator_flags.log"
TANGLISH_AUDIT_LOG = NORMALIZATION_DIR / "tanglish_audit.log"
TANGLISH_GOLD_PAIRS_PATH = NORMALIZATION_DIR / "tanglish_gold_pairs.json"
TRANSLATION_DEBUG_LOG = NORMALIZATION_DIR / "translation_debug.log"

# OpenSLR Tamil G2P lexicon (via harveenchadha/indic-voice).
# VERIFY THIS URL MANUALLY before fetching — upstream hosting may move.
OPENSLR_TAMIL_G2P_URL = (
    "https://www.openslr.org/resources/37/ta_lexicon.tsv"
)
# Alternate documented source for merge guidance:
INDIC_VOICE_LEXICON_NOTE = (
    "https://github.com/harveenchadha/indic-voice"
)

# ---------------------------------------------------------------------------
# Ollama / LLM (no API key — local REST)
# ---------------------------------------------------------------------------
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_CHAT_URL = f"{OLLAMA_BASE_URL.rstrip('/')}/api/chat"
OLLAMA_GENERATE_URL = f"{OLLAMA_BASE_URL.rstrip('/')}/api/generate"
# Prefer a small local model for low-latency Tanglish rewrite (override via .env).
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
OLLAMA_TIMEOUT_SEC = float(os.getenv("OLLAMA_TIMEOUT_SEC", "60"))
LLM_MAX_RETRIES = 2

# ---------------------------------------------------------------------------
# Language translator (between input and TTS)
# ---------------------------------------------------------------------------
TRANSLATOR_ENABLED = os.getenv("TRANSLATOR_ENABLED", "true").lower() in ("1", "true", "yes")
# Keep OFF for low TTFA — offline Tanglish rewrite is instant; Ollama adds seconds.
TRANSLATOR_OLLAMA_ENABLED = os.getenv("TRANSLATOR_OLLAMA_ENABLED", "false").lower() in (
    "1",
    "true",
    "yes",
)
# tanglish | en | ta | auto
DEFAULT_TARGET_LANG = os.getenv("DEFAULT_TARGET_LANG", "tanglish")

# ---------------------------------------------------------------------------
# Tanglish translation (English → spoken Chennai Tanglish)
#
# Every request is built from the current utterance alone. No conversation
# history, no previous translation, and no previous model output is ever fed
# back in — see normalization/tanglish_translator.py.
# ---------------------------------------------------------------------------


def _flag(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


# Falls back to OLLAMA_MODEL so a single env var still switches everything.
TANGLISH_MODEL = os.getenv("TANGLISH_MODEL", OLLAMA_MODEL)
# Deterministic decoding — translation is not a creative task.
TANGLISH_TEMPERATURE = float(os.getenv("TANGLISH_TEMPERATURE", "0.0"))
TANGLISH_TOP_P = float(os.getenv("TANGLISH_TOP_P", "0.9"))
TANGLISH_TOP_K = int(os.getenv("TANGLISH_TOP_K", "40"))
TANGLISH_REPEAT_PENALTY = float(os.getenv("TANGLISH_REPEAT_PENALTY", "1.1"))
TANGLISH_SEED = int(os.getenv("TANGLISH_SEED", "7"))
# Must match the Ollama runner created at warmup. Changing num_ctx between
# calls forces a full VRAM reload (~7–9s) even when keep_alive=-1.
TANGLISH_NUM_CTX = int(os.getenv("TANGLISH_NUM_CTX", "4096"))
TANGLISH_TIMEOUT_SEC = float(os.getenv("TANGLISH_TIMEOUT_SEC", str(OLLAMA_TIMEOUT_SEC)))


def _keep_alive(raw: str | None) -> str | int:
    """Ollama accepts duration strings ('30m') or int -1 (forever).

    The string '-1' is rejected ('missing unit in duration'), which made every
    Tanglish call 400 and fall back to shredded offline text.
    """
    v = (raw if raw is not None else os.getenv("TANGLISH_KEEP_ALIVE", "30m")).strip()
    if v in ("-1", "forever", "infinite", "inf"):
        return -1
    if v.lstrip("-").isdigit():
        return int(v)
    return v or "30m"


# Pin the model in VRAM between utterances. Reloading costs ~40s on this
# hardware, which is fatal for a live call; inference itself is ~1.5s.
TANGLISH_KEEP_ALIVE = _keep_alive(os.getenv("TANGLISH_KEEP_ALIVE", "30m"))

# Retrieval-grounded few-shot: k nearest gold pairs for the CURRENT sentence.
# Derived only from the current source text, so it cannot leak across requests.
TANGLISH_FEWSHOT_K = int(os.getenv("TANGLISH_FEWSHOT_K", "2"))

# Bounded retries when validation fails. Retries are never recursive.
# Default 0 for live TTFA: a failed call falls straight to offline/gold rather
# than paying another multi-second model round-trip.
TANGLISH_MAX_RETRIES = int(os.getenv("TANGLISH_MAX_RETRIES", "0"))

# Non-Ollama Tanglish audit (gold / offline): meaning + Tamil/English mix ratio.
TANGLISH_AUDIT_ENABLED = _flag("TANGLISH_AUDIT_ENABLED", "true")
# Min Tamil-token share among content words (calibrated: gold corpus p10 ~0.55).
TANGLISH_MIX_TAMIL_MIN = float(os.getenv("TANGLISH_MIX_TAMIL_MIN", "0.45"))
# Max English-loanword share before flagging passthrough English.
TANGLISH_MIX_ENGLISH_MAX = float(os.getenv("TANGLISH_MIX_ENGLISH_MAX", "0.70"))

# Hallucination signals (thresholds, not absolute rules).
TANGLISH_EXPANSION_RATIO = float(os.getenv("TANGLISH_EXPANSION_RATIO", "2.0"))
TANGLISH_SHRINK_RATIO = float(os.getenv("TANGLISH_SHRINK_RATIO", "0.40"))
TANGLISH_REPEAT_LIMIT = int(os.getenv("TANGLISH_REPEAT_LIMIT", "4"))

# Identical input → identical output (and no repeat model call).
TANGLISH_CACHE_ENABLED = _flag("TANGLISH_CACHE_ENABLED", "true")
TANGLISH_CACHE_SIZE = int(os.getenv("TANGLISH_CACHE_SIZE", "512"))

# Prefer instant gold/offline when good enough; only call Ollama for leftovers.
# Set false to force every utterance through the model (higher quality, ~2–9s).
TANGLISH_OLLAMA_ONLY_WHEN_NEEDED = _flag("TANGLISH_OLLAMA_ONLY_WHEN_NEEDED", "true")

# Per-request SOURCE/MODEL/VALIDATION/RETRY/FINAL/LATENCY trace.
# Logs utterance text — keep OFF in production.
TANGLISH_DEBUG = _flag("TANGLISH_DEBUG", "false")

# ---------------------------------------------------------------------------
# TTS backends
# ---------------------------------------------------------------------------
DEFAULT_TTS_BACKEND = os.getenv(
    "DEFAULT_TTS_BACKEND",
    # Windows: local SAPI is ~20–150ms; elsewhere prefer edge neural.
    "win_sapi" if sys.platform.startswith("win") else "edge_fast",
)
F5_MODEL_ID = os.getenv("F5_MODEL_ID", "ai4bharat/IndicF5")
# edge-tts neural voices (fast path — no local GPU)
EDGE_DEFAULT_VOICE = os.getenv("EDGE_DEFAULT_VOICE", "ta-IN-PallaviNeural")
# Background cache priming blocks the GPU — keep OFF for low TTFA
CACHE_PRIME_BACKGROUND = os.getenv("CACHE_PRIME_BACKGROUND", "false").lower() in (
    "1",
    "true",
    "yes",
)
DEFAULT_VOICE_STYLE = os.getenv(
    "DEFAULT_VOICE_STYLE",
    # Named speaker caption used by Edge voice mapping (Jaya → PallaviNeural).
    "Jaya speaks in a clear, calm, moderate-pitched voice at a moderate pace. "
    "The recording is of very high quality with no background noise.",
)
# MMS Tamil is intentionally NOT integrated — CC-BY-NC-4.0 is incompatible
# with Movio as a commercial acquisition target.
MMS_TAMIL_EXCLUDED = True

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------
SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
# Default 8001 — port 8000 is often taken by other local tools on Windows.
SERVER_PORT = int(os.getenv("SERVER_PORT", "8001"))
# Phase 3: enable bounded queue. Phase 1/2 can run with QUEUE_ENABLED=false.
QUEUE_ENABLED = os.getenv("QUEUE_ENABLED", "true").lower() in ("1", "true", "yes")
QUEUE_WORKER_COUNT = int(os.getenv("QUEUE_WORKER_COUNT", "1"))
QUEUE_MAX_SIZE = int(os.getenv("QUEUE_MAX_SIZE", "32"))
QUEUE_REQUEST_TIMEOUT_SEC = float(os.getenv("QUEUE_REQUEST_TIMEOUT_SEC", "60"))

# ---------------------------------------------------------------------------
# Cache (Phase 2) — important for repeating taxi phrases
# ---------------------------------------------------------------------------
CACHE_ENABLED = os.getenv("CACHE_ENABLED", "true").lower() in ("1", "true", "yes")
CACHE_MAX_ENTRIES = int(os.getenv("CACHE_MAX_ENTRIES", "512"))
# Clause + template/slot cache (after full-utterance miss). Keeps phrase-sized
# units for natural prosody; never word-by-word stitching.
CLAUSE_CACHE_ENABLED = os.getenv("CLAUSE_CACHE_ENABLED", "true").lower() in (
    "1",
    "true",
    "yes",
)
TEMPLATE_CACHE_ENABLED = os.getenv("TEMPLATE_CACHE_ENABLED", "true").lower() in (
    "1",
    "true",
    "yes",
)
# Silence inserted between stitched clause/template units (milliseconds).
CACHE_STITCH_GAP_MS = float(os.getenv("CACHE_STITCH_GAP_MS", "90"))

# ---------------------------------------------------------------------------
# Data generation
# ---------------------------------------------------------------------------
SENTENCES_PER_CATEGORY = int(os.getenv("SENTENCES_PER_CATEGORY", "28"))
CATEGORIES = [
    "booking",
    "cancellation",
    "driver_arrival",
    "pickup",
    "drop",
    "payment",
    "otp",
    "traffic",
    "complaints",
    "general_conversation",
]

# ---------------------------------------------------------------------------
# Concurrency / load test (Phase 3)
# ---------------------------------------------------------------------------
CONCURRENCY_LEVELS = [1, 5, 10, 15, 20]
LOAD_TEST_RUNS_PER_LEVEL = 3
LOAD_TEST_SAMPLE_TEXTS = [
    "Your driver has arrived at the pickup point.",
    "Please share your OTP 4821 with the driver.",
    "Unga cab Velachery la five minutes la varum.",
    "Booking confirmed for tomorrow 9 AM to Guindy.",
    "Traffic heavy ah irukku on OMR, delay aagum.",
]

# ---------------------------------------------------------------------------
# Optimization subset size
# ---------------------------------------------------------------------------
OPTIMIZATION_SENTENCE_COUNT = int(os.getenv("OPTIMIZATION_SENTENCE_COUNT", "25"))

# ---------------------------------------------------------------------------
# Cost analysis (Phase 4)
# ---------------------------------------------------------------------------
# PLACEHOLDER — local LOQ testing is ~$0 marginal cost but NOT representative
# of production. Typical cloud GPU tiers (T4 / A10G) run roughly $0.50–1.50/hour.
# Set HARDWARE_COST_PER_HOUR based on the intended deployment target before
# finalizing cost numbers.
HARDWARE_COST_PER_HOUR = float(os.getenv("HARDWARE_COST_PER_HOUR", "1.00"))

# ---------------------------------------------------------------------------
# Evaluation / ASR
# ---------------------------------------------------------------------------
ASR_PRIMARY_MODEL = os.getenv("ASR_PRIMARY_MODEL", "ai4bharat/indicwhisper")
ASR_FALLBACK_MODEL = os.getenv("ASR_FALLBACK_MODEL", "openai/whisper-small")

# ---------------------------------------------------------------------------
# TTFA target (informational)
# ---------------------------------------------------------------------------
TTFA_TARGET_MS = 100

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
