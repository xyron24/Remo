"""Languages: per-locale voices plus every user-facing string.

Hinglish + Marathi ship fully translated across turns, recall, work-log, watcher,
and briefing. Quiz verdicts and reminder read-backs stay Hinglish-first until a
native speaker reviews them — they fall back automatically (never crash).
"""
from __future__ import annotations

HI = {
    "ack_saved": "Yaad kar liya.",
    "ack_saved_work": "Yaad kar liya, kaam ki list mein jod diya.",
    "prompt_repeat": "Uske baad kya yaad rakhna hai, ek baar phir bolo?",
    "confirm_undo": "Aakhri wali baat bhula doon?",
    "undone": "Bhula diya.",
    "kept": "Rehne diya, yaad rahega.",
    "help": "Kuch yaad karwane ke liye 'yaad rakhna' se shuru karo. Puchhne ke liye bas bol do, jaise 'kya bacha hai?'",
    "nothing_named": "Is naam se kuch yaad nahi hai.",
    "ask_when": "Kab yaad dilaun? Waqt samajh nahi aaya.",
    "ask_task": "Kis liye yaad dilaun?",
    "ask_yes_no": "Haan ya nahi?",
    "reminders_off": "Theek hai, reminder nahi lagaya.",
    "no_work_record": "Is kaam ka koi record nahi mila.",
    "bad_watch_url": "Ye link samajh nahi aaya. GitHub issue ya repo ka link bolo.",
    "nothing_watched": "Abhi kuch watch nahi kar raha. 'Watch karo' ke baad link bolo.",
    "watching_ok": "Ho gaya, is par nazar rakhunga. 'Koi update' bolkar haal pucho.",
    "remind_done": "Ho gaya, waqt par yaad dila dunga.",
    "remind_armed": "Ho gaya: {readback} — {task}.",
    "remind_confirm": "{readback}: {task}. Pakka?",
    "forget_ask": "'{text}' — bhula doon?",
    "left_off_none": "Abhi maine kuch yaad nahi kiya. 'Yaad rakhna' bolkar shuru karo.",
    "left_off_pending": "Ye baaki hai: {items}.",
    "left_off_extra": " Aur {n} purani baatein yaad hain.",
    "left_off_all_done": "Kuch baaki nahi dikh raha. Aakhri baat thi: {latest}.",
    "recall_none": "Is baare mein mujhe kuch yaad nahi hai.",
    "recall_found": "Mujhe ye mila: {items}",
    "entry_fallback": "ye kaam",
    "entry_none": "{label} mein abhi kuch darj nahi hai.",
    "entry_pending": "{label} mein ye baaki hai: {items}.",
    "entry_done": "Ho gaya: {items}.",
    "welcome_none": "Welcome back! Kuch baaki nahi hai aur bahar bhi koi badlaav nahi.",
    "welcome_head": "Welcome back!",
    "welcome_pending": "Aapke {n} kaam baaki hain: {items}.",
    "welcome_deltas": "Bahar {n} badlaav aaye hain: {items}.",
    "welcome_next": "Pehle ye karo: {item}.",
    "baseline_issue": "Issue #{number} {state} hai, {n} comments ke saath. Ab se nazar rahegi.",
    "state_change": "Issue #{number} ab {state} hai: {title}.",
    "new_comment": "Issue #{number} par {who} ka naya comment.",
    "repo_baseline": "Repo par nazar shuru. Taaza commit: {msg}.",
    "new_commit": "Naya commit {sha}: {msg}.",
    "updates_none": "Koi naya badlaav nahi hai.",
    "updates_some": "{n} badlaav aaye hain ({label}): {firsts}.{extra}",
    "updates_extra": " Aur {n} aur.",
    "updates_offline_alone": "Source se sampark nahi ho paya, isliye sirf yaad se bata raha hoon. ",
    "updates_offline_partial": " Kuch sources se sampark nahi hua.",
    "plan_rems": "Aaj ke liye {n} reminders: {items}.",
    "plan_no_rems": "Aaj ke liye koi reminder nahi hai.",
    "plan_notes": "Aakhri baatein: {items}.",
    "plan_no_notes": "Abhi kuch yaad nahi karwaya.",
}

MR = {
    "ack_saved": "Lakshat thevla.",
    "ack_saved_work": "Lakshat thevla, kamachya yadit jodla.",
    "prompt_repeat": "Tyanantar kay lakshat thevaycha aahe, ekda parat bola?",
    "confirm_undo": "Shevatchi goshta visru ka?",
    "undone": "Visarlo.",
    "kept": "Rahu dila, lakshat rahil.",
    "help": "Kahi lakshat thevaycha asel tar 'lakshat thev' ne suruvat kara. Vicharaycha asel tar fakt bola, jasa 'kay rahila aahe?'",
    "nothing_named": "Ya navane kahi aathavat nahi.",
    "ask_when": "Kevha aathvan karun? Vel samajli nahi.",
    "ask_task": "Kashasathi aathvan karun?",
    "ask_yes_no": "Hoy ki nahi?",
    "reminders_off": "Theek aahe, reminder lavla nahi.",
    "no_work_record": "Ya kamacha kahi record sapadla nahi.",
    "bad_watch_url": "Hi link samajli nahi. GitHub issue kiwa repo chi link sanga.",
    "nothing_watched": "Aata kahi watch karat nahi. 'Watch karo' nantar link sanga.",
    "watching_ok": "Zala, yavar laksh thevin. 'Kahi update' mhanoon vichara.",
    "remind_done": "Zala, velet aathvan karin.",
    "remind_armed": "Zala: {readback} — {task}.",
    "remind_confirm": "{readback}: {task}. Nakki?",
    "forget_ask": "'{text}' — visru ka?",
    "left_off_none": "Aata mi kahi lakshat thevla nahi. 'Lakshat thev' mhanoon suruvat kara.",
    "left_off_pending": "He rahila aahe: {items}.",
    "left_off_extra": " Aani {n} junya goshti lakshat aahet.",
    "left_off_all_done": "Kahi rahilela disat nahi. Shevatchi goshta hoti: {latest}.",
    "recall_none": "Ya baddal mala kahi aathavat nahi.",
    "recall_found": "Mala he sapadla: {items}",
    "entry_fallback": "he kaam",
    "entry_none": "{label} madhe aata kahi nond nahi.",
    "entry_pending": "{label} madhe he rahila aahe: {items}.",
    "entry_done": "Zala: {items}.",
    "welcome_none": "Welcome back! Kahi rahila nahi aani baherhi kahi badal nahi.",
    "welcome_head": "Welcome back!",
    "welcome_pending": "Tumchi {n} kama rahili aahet: {items}.",
    "welcome_deltas": "Baher {n} badal aale aahet: {items}.",
    "welcome_next": "Aadhi he kara: {item}.",
    "baseline_issue": "Issue #{number} {state} aahe, {n} comments saha. Aata laksh thevin.",
    "state_change": "Issue #{number} aata {state} aahe: {title}.",
    "new_comment": "Issue #{number} var {who} chi navi comment.",
    "repo_baseline": "Repo var laksh suru. Taza commit: {msg}.",
    "new_commit": "Navin commit {sha}: {msg}.",
    "updates_none": "Kahi navin badal nahi.",
    "updates_some": "{n} badal aale aahet ({label}): {firsts}.{extra}",
    "updates_extra": " Aani {n} aankhi.",
    "updates_offline_alone": "Strotashi sampark zala nahi, mhanun fakt aathvanitun sangto. ",
    "updates_offline_partial": " Kahi strotanshi sampark zala nahi.",
    "plan_rems": "Aajsathi {n} reminders: {items}.",
    "plan_no_rems": "Aajsathi kahi reminder nahi.",
    "plan_notes": "Shevatya goshti: {items}.",
    "plan_no_notes": "Aata kahi lakshat thevla nahi.",
}

TABLES = {"hi": HI, "mr": MR}

PROFILES = {
    "hi-IN": {"tts_voice": "Nalini", "boost_lang": "hi"},
    "mr-IN": {"tts_voice": "Zahira", "boost_lang": "mr"},
}

DEFAULT_VOICE = "Nalini"


def lang_key(code: str | None) -> str:
    """'mr-IN' -> 'mr'; unknown codes fall back to 'hi'."""
    key = (code or "hi").split("-")[0].lower()
    return key if key in TABLES else "hi"


def strings(code: str | None = "hi-IN") -> dict[str, str]:
    """Full string table for a locale; missing keys fall back to Hinglish."""
    table = dict(HI)
    table.update(TABLES.get(lang_key(code), {}))
    return table


def profile(code: str | None = "hi-IN") -> dict[str, str]:
    """Voice + boost settings for a locale; unknown codes use Hinglish."""
    return dict(PROFILES.get(code or "hi-IN", PROFILES["hi-IN"]))


def resolve_voice(explicit_voice: str = "", code: str | None = "hi-IN") -> str:
    """Explicit voice wins; otherwise the best voice for the locale."""
    if explicit_voice:
        return explicit_voice
    return profile(code).get("tts_voice", DEFAULT_VOICE)
