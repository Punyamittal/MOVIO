# Reference voices for IndicF5 (comparison backbone)

Place a short clean reference clip here:

- `reference.wav` — 3–10 seconds of clear Tamil/Tanglish speech, mono preferred
- `reference.txt` — exact transcript of that clip

IndicF5 needs reference audio + transcript for voice conditioning.
Without these files the backend falls back to a silent mock WAV so the rest of
the pipeline remains independently testable offline.

Do NOT commit large proprietary voice recordings without rights clearance.
