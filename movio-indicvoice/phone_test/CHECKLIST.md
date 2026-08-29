# Two-Phone Local Testing Checklist

Use this after `python -m phone_test` (or `python -m server.main` with phone routes) is running.

## Basic connection

- [ ] Laptop dashboard opens at `/test/`
- [ ] FSM shows `IDLE`
- [ ] Two QR codes visible (Phone A / Phone B)
- [ ] Phone A scans QR A and shows Connected
- [ ] Phone B scans QR B and shows Connected
- [ ] Dashboard shows both phones Connected

## Half-duplex continuous VAD (default)

On each phone: tap **Enable microphone / audio**, then **ENABLE LISTENING**.

1. A speaks → pauses ~1s → B hears TTS only (A does not)
2. B speaks → pauses ~1s → A hears TTS only
3. FSM path roughly: `IDLE → LISTENING_A → PROCESSING → TRANSLATING → TTS_B → IDLE → LISTENING_B → …`

## Hold-to-speak fallback

- [ ] Switch phone to **Hold to speak**
- [ ] Hold → release still finalizes one utterance

## Edge cases

1. **Overlap** — both start together: first speaker kept; other flagged `OVERLAP` / interruption (not mixed)
2. **Barge-in** — during partner TTS, speak loudly: TTS stops, floor switches (`BARGE_IN`)
3. **Echo** — receiving phone mic must not re-translate TTS (`echo gate ON` while playing)
4. **Silence endpoint** — continuous speech waits for ~900ms silence before ASR (not every chunk)
5. **Short replies** — “yes”, “no”, “okay”, “where?” still process
6. **Noise** — quiet background should be rejected (VAD / min duration)
7. **Same language** — if source≈target family, translation skipped (passthrough TTS ok)
8. **Uncertain language** — ASR kept, translation withheld, error/retry shown
9. **Tanglish** — OTP / cab / parking / Chennai place names preserved through norm+translate
10. **Translate failure** — ASR text preserved; Retry available
11. **TTS failure** — translated text shown; Retry resynthesizes
12. **Duplicate** — same `utterance_id` never translated twice
13. **Disconnect/reconnect** — session resumes; stale TTS not replayed

## One-way sample (A → B)

> Unga driver 5 minutes la vandhuruvaanga. OTP 4821 share pannunga.

- [ ] Dashboard shows utterance_id, transcript, normalized, translation, status
- [ ] Phone B plays translated audio; Phone A does not

## Reverse sample (B → A)

> Your driver will arrive in five minutes. Please share the OTP.

- [ ] Phone A plays Tanglish/Tamil audio

## Debug

- [ ] Dashboard debug log shows FSM transitions
- [ ] Each utterance has `utterance_id`, `speaker_id`, langs, transcript, translation, `processing_status`
- [ ] Text self-test button still passes A→B and B→A
