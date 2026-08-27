# Two-Phone Local Testing Checklist

Use this after `python -m phone_test` is running.

## Basic connection

- [ ] Laptop dashboard opens at `/test/`
- [ ] Two QR codes visible (Phone A / Phone B)
- [ ] Phone A scans QR A and shows Connected
- [ ] Phone B scans QR B and shows Connected
- [ ] Dashboard shows both phones Connected

## One-way translation (A → B)

Speak Tamil/Tanglish on Phone A (hold-to-speak):

> Unga driver 5 minutes la vandhuruvaanga. OTP 4821 share pannunga.

- [ ] Dashboard shows STT text
- [ ] English (or configured output) translation appears
- [ ] Phone B plays translated audio

## Reverse translation (B → A)

Speak English on Phone B:

> Your driver will arrive in five minutes. Please share the OTP.

- [ ] Tamil/Tanglish translation generated
- [ ] Phone A plays translated audio

## Longer sentence

- [ ] Multi-clause speech completes without crashing either phone

## Interruptions / reconnect

- [ ] Disconnect Phone B mid-session — dashboard shows disconnected
- [ ] Refresh Phone B — reconnects to same session with same QR/token
- [ ] Duplicate open of Phone A replaces prior connection cleanly

## Permission

- [ ] Deny microphone — UI shows permission message
- [ ] On Chrome LAN HTTP mic block — HTTPS mode or insecure-origin flag documented

## Latency

- [ ] Last / average latency displayed on phone and dashboard

## Concurrent directions

- [ ] Alternating A→B and B→A does not corrupt session state

## Automated (no phones)

```bash
# Terminal 1
python -m phone_test --no-browser

# Terminal 2
python -m phone_test.simulate
# or: python -m phone_test --simulate-only
```

- [ ] Self-test reports PASS for A→B and B→A text pipeline
