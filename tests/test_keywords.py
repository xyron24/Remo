"""Keyword gate: save triggers, content checks, forget/undo patterns."""
import pytest

from remo.brain_keywords import (
    check_content,
    is_undo_last,
    match_forget,
    match_save_keyword,
)


@pytest.mark.parametrize(
    ("said", "expected"),
    [
        ("yaad rakhna maths mein integration ho gaya", "maths mein integration ho gaya"),
        ("Yaad Rakhna, Go assignment kal hai", "Go assignment kal hai"),
        ("YAAD RAKHNA:  call mom at 5", "call mom at 5"),
        ("remember the meeting is at 5", "the meeting is at 5"),
        ("Remember, issue 214 docs are pending", "issue 214 docs are pending"),
        ("याद रखना गणित में काम बाकी है", "गणित में काम बाकी है"),
        ("lakshat thev, ganitat kaam baki aahe", "ganitat kaam baki aahe"),
        ("लक्षात ठेव गणितात काम बाकी आहे", "गणितात काम बाकी आहे"),
        ("रिमेम्बर मुझे कल नये प्रोजेक्ट पर काम करना है", "मुझे कल नये प्रोजेक्ट पर काम करना है"),
        ("रिमेंबर आई हैव टू वर्क अपॉन अ प्रोजेक्ट टुमॉरो", "आई हैव टू वर्क अपॉन अ प्रोजेक्ट टुमॉरो"),
    ],
)
def test_save_keyword_returns_original_case_content(said: str, expected: str) -> None:
    assert match_save_keyword(said) == expected


@pytest.mark.parametrize(
    "said",
    [
        "maths mein kya bacha hai?",
        "please yaad rakhna this for me",  # not utterance-initial
        "do you remember the meeting?",  # not utterance-initial
        "aaj ka plan batao",
        "",
    ],
)
def test_non_keyword_passes_through(said: str) -> None:
    assert match_save_keyword(said) is None


def test_bare_keyword_needs_repeat() -> None:
    content = match_save_keyword("yaad rakhna")
    assert content == ""
    assert check_content(content or "") == "empty"


@pytest.mark.parametrize(
    ("content", "verdict"),
    [("", "empty"), ("   ", "empty"), ("x", "too-short"), ("call mom", None)],
)
def test_content_gate(content: str, verdict: str | None) -> None:
    assert check_content(content) == verdict


@pytest.mark.parametrize(
    "said",
    [
        "bhool jao last wali baat",
        "Last Wali Baat Bhool Jao",
        "forget last",
        "forget the last one",
        "shevatchi goshta visar",
        "आखिरी वाली बात भूल जाओ",
    ],
)
def test_undo_last_patterns(said: str) -> None:
    assert is_undo_last(said)


@pytest.mark.parametrize(
    ("said", "expected"),
    [
        ("bhool jao maths wali baat", "maths wali baat"),
        ("Forget Issue 214 notes", "Issue 214 notes"),
        ("visar kalchi goshta", "kalchi goshta"),
        ("भूल जाओ कल वाली बात", "कल वाली बात"),
    ],
)
def test_forget_target_extraction(said: str, expected: str) -> None:
    assert match_forget(said) == expected


def test_forget_needs_target() -> None:
    assert match_forget("bhool jao") is None
    assert match_forget("forget") is None
