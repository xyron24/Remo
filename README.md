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

## On the way

Telephony-grade noise handling, call-me-back reminders, and a full regional-language experience.

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
