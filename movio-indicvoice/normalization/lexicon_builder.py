"""
Documented helper to fetch/merge OpenSLR Tamil G2P lexicon into pronunciation_lexicon.json.

Does not auto-overwrite filled entries. URL is a config constant — verify manually.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import (  # noqa: E402
    INDIC_VOICE_LEXICON_NOTE,
    OPENSLR_TAMIL_G2P_URL,
    PRONUNCIATION_LEXICON_PATH,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("normalization.lexicon_builder")


def fetch_openslr_preview(url: str = OPENSLR_TAMIL_G2P_URL, max_lines: int = 20) -> list[str]:
    """
    Attempt a preview fetch of the OpenSLR Tamil lexicon.

    VERIFY OPENSLR_TAMIL_G2P_URL in config.py manually before relying on this —
    upstream hosting may move. See also INDIC_VOICE_LEXICON_NOTE:
    {note}
    """.format(note=INDIC_VOICE_LEXICON_NOTE)
    try:
        with urlopen(url, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
        lines = [ln for ln in raw.splitlines() if ln.strip()][:max_lines]
        logger.info("Fetched %d preview lines from %s", len(lines), url)
        return lines
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Could not fetch OpenSLR lexicon from %s: %s. "
            "Merge manually from %s into %s",
            url,
            exc,
            INDIC_VOICE_LEXICON_NOTE,
            PRONUNCIATION_LEXICON_PATH,
        )
        return []


def merge_into_lexicon(
    new_entries: dict[str, str],
    lexicon_path: Path = PRONUNCIATION_LEXICON_PATH,
    overwrite: bool = False,
) -> Path:
    """Merge entries; by default do not overwrite non-empty existing values."""
    if lexicon_path.exists():
        data = json.loads(lexicon_path.read_text(encoding="utf-8"))
    else:
        data = {}
    for key, val in new_entries.items():
        if not overwrite and data.get(key):
            continue
        data[key] = val
    lexicon_path.parent.mkdir(parents=True, exist_ok=True)
    lexicon_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Merged %d entries into %s", len(new_entries), lexicon_path)
    return lexicon_path


def document_merge_process() -> None:
    print(
        """
How to merge OpenSLR Tamil G2P into pronunciation_lexicon.json
==============================================================
1. Verify OPENSLR_TAMIL_G2P_URL in config.py (may move).
2. Optionally browse harveenchadha/indic-voice for packaged lexicons.
3. Download the TSV/lexicon and map grapheme → preferred pronunciation spelling.
4. Call merge_into_lexicon({...}) or edit pronunciation_lexicon.json by hand.
5. Leave empty-string placeholders for entries you have not verified yet —
   deterministic_normalizer.apply_lexicon skips empty values.

This step is OPTIONAL and never blocks the core TTS pipeline.
""".strip()
    )


if __name__ == "__main__":
    document_merge_process()
    preview = fetch_openslr_preview()
    if preview:
        print("Preview (first lines):")
        for line in preview[:5]:
            print(" ", line[:120])
