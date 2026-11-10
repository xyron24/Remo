# Remo

Speak once. Remember forever. Know what changed.

Remo is a Hinglish + regional-language voice memory built solo for the Great Indian AI Internship Challenge 2026 on
Gnani AI's Prisma (speech-to-text), Timbre (text-to-speech), and Evon (reasoning).

_Runs anywhere — backend on macOS, Windows, or Linux; use it from any browser or phone, Android and iOS included._

## What Remo does

- **Keyword auto-save** — start with "yaad rakhna" / "remember" (Hindi, Hinglish, or English) and everything after it
  is stored instantly. No confirmation questions; voice undo ("bhool jao last wali baat") has you covered.
- **Local-first memory** — notes live on your own machine in SQLite, stored in Devanagari + Latin with meaning search,
  so "maths" finds "मैथ्स".
- **Realtime transcription** — Gnani Prisma streams your voice to text over WebSocket, with vocabulary from your own
  notes boosted so it keeps hearing *you* better.
- **Spoken answers** — ask "kya bacha hai?" and Remo replies out loud, pending items first, in a Timbre voice.
- **Reminders** — "kal subah 9 baje chai yaad dilana" and it chimes + speaks at 9, even after a restart.
- **Day's plan & quiz** — "aaj ka plan batao" briefs the day; "quiz karo" tests you on your own notes.
- **Work-log memory** — speak a progress update and Remo tracks done vs pending per project; "issue 214 mein kya bacha
  hai?" answers from the log, weeks later.
- **Change watcher** — "watch karo" a GitHub issue or repo and Remo briefs only what changed since you were last here,
  with links. "Welcome back" merges your pending items, outside changes, and a suggested next step.
- **Hindi + Marathi, end to end** — every reply, briefing, and confirmation speaks both languages (Timbre voices Nalini
  and Zahira); "lakshat thev" saves just like "yaad rakhna".
- **Learns your voice** — vocabulary from your notes boosts recognition, and stubborn mishearings become automatic
  fixes you can inspect.
- **Noise benchmark in-repo** — `python scripts/noise_bench.py` scores Prisma on fan/traffic/crowd noise at 16 and
  8 kHz and writes a WER report + chart.

## On the way

Live phone-call interface, PDF note imports, and Evon-powered reasoning upgrades.

## Quickstart

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # paste your key from https://app.gnani.ai/voice
python -m pytest -q             # offline tests
python -m pytest -m live -q     # live Gnani round-trip (needs the key)
```

## Powered by Gnani AI

| Model | Role in Remo |
|---|---|
| Prisma (STT) | Realtime + REST transcription, word boosting, find-and-replace |
| Timbre (TTS) | Every spoken reply, confirmation, and reminder |
| Evon (reasoning) | Understanding, recall, briefings, and change summaries |

## Privacy

Your notes, reminders, and keys stay on your machine. Voice goes to Gnani for transcription, text goes to Gnani for
speech, and understanding runs on Gnani's own Evon model. The demo uses made-up data only.
