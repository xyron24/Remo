# Remo

Speak once. Remember forever. Know what changed.

Remo is a Hinglish + regional-language voice memory built solo for the Great Indian AI Internship Challenge 2026 on
Gnani AI's Prisma (speech-to-text), Timbre (text-to-speech), and Evon (reasoning).

## What Remo does

- **Keyword auto-save** — start with "yaad rakhna" / "remember" (Hindi, Hinglish, or English) and everything after it
  is stored instantly. No confirmation questions; voice undo ("bhool jao last wali baat") has you covered.
- **Local-first memory** — notes live on your own machine in SQLite, stored in Devanagari + Latin with meaning search,
  so "maths" finds "मैथ्स".
- **Realtime transcription** — Gnani Prisma streams your voice to text over WebSocket, with vocabulary from your own
  notes boosted so it keeps hearing *you* better.

## On the way

Spoken answers and reminders, voice quiz, work-log memory ("where did I leave off?"), change tracking ("what changed
while you were away"), and a full regional-language experience.

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
