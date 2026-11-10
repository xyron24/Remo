"""Change watcher: poll public sources, brief only what is new.

V1 watches GitHub issues (state + comments) and repos (commits). Each watched
URL keeps a seen-state cursor; polls store deltas with source quotes + links.
Unreachable sources degrade honestly to local memory with an as-of disclaimer.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import requests

from remo import lang as lang_mod
from remo.log import get_logger
from remo.memory import Change, Memory, WatchedItem

log = get_logger("watcher")

API = "https://api.github.com"
_TIMEOUT = 20

_GITHUB_ISSUE = re.compile(r"github\.com/([\w.-]+)/([\w.-]+)/(?:issues|pull)/(\d+)", re.I)
_GITHUB_REPO = re.compile(r"github\.com/([\w.-]+)/([\w.-]+)/?$", re.I)


@dataclass
class Delta:
    summary: str
    quote: str = ""
    link: str = ""
    at: float = 0.0


@dataclass
class PollReport:
    checked: int = 0
    new_changes: int = 0
    errors: list[str] = field(default_factory=list)
    checked_at: float = 0.0


def kind_for_url(url: str) -> str | None:
    """github_issue | github_repo | None (unsupported host/shape)."""
    if _GITHUB_ISSUE.search(url):
        return "github_issue"
    if _GITHUB_REPO.search(url):
        return "github_repo"
    return None


def _fetch(url: str, params: dict | None = None, token: str = "") -> object:
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resp = requests.get(url, headers=headers, params=params or {}, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _parse_cursor(raw: str) -> dict:
    try:
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {}


def _iso_to_ts(value: str) -> float:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def poll_github_issue(
    url: str, cursor: str, token: str = "", fetch=_fetch, lang: str = "hi"
) -> tuple[str, list[Delta]]:
    """New state/title/comments on one issue or PR since the cursor."""
    match = _GITHUB_ISSUE.search(url)
    if not match:
        raise ValueError(f"not a GitHub issue URL: {url}")
    s = lang_mod.strings(lang)
    owner, repo, number = match.groups()
    seen = _parse_cursor(cursor)
    deltas: list[Delta] = []

    issue = fetch(f"{API}/repos/{owner}/{repo}/issues/{number}")
    state, title = issue.get("state", ""), issue.get("title", "")
    comments = fetch(f"{API}/repos/{owner}/{repo}/issues/{number}/comments", {"per_page": "100"})
    if not seen:
        deltas.append(
            Delta(summary=s["baseline_issue"].format(number=number, state=state, n=len(comments)),
                  link=issue.get("html_url", url), at=time.time())
        )
    elif seen.get("state") != state or seen.get("title") != title:
        deltas.append(
            Delta(summary=s["state_change"].format(number=number, state=state, title=title),
                  link=issue.get("html_url", url), at=time.time())
        )
    last_id = int(seen.get("last_comment_id", 0))
    fresh = [c for c in comments if int(c.get("id", 0)) > last_id] if seen else []
    for comment in fresh:
        who = (comment.get("user") or {}).get("login", "koi")
        body = (comment.get("body") or "").strip().splitlines()
        first_line = body[0][:160] if body else ""
        deltas.append(
            Delta(summary=s["new_comment"].format(number=number, who=who),
                  quote=first_line, link=comment.get("html_url", url),
                  at=_parse_time(comment.get("created_at", "")))
        )
    new_cursor = json.dumps({
        "state": state, "title": title,
        "last_comment_id": max([last_id] + [int(c.get("id", 0)) for c in comments]),
        "checked": _now_iso(),
    })
    return new_cursor, deltas


def _parse_time(value: str) -> float:
    return _iso_to_ts(value) or time.time()


def poll_github_repo(
    url: str, cursor: str, token: str = "", fetch=_fetch, lang: str = "hi"
) -> tuple[str, list[Delta]]:
    """New commits on the default branch since the cursor."""
    match = _GITHUB_REPO.search(url)
    if not match:
        raise ValueError(f"not a GitHub repo URL: {url}")
    s = lang_mod.strings(lang)
    owner, repo = match.groups()
    seen = _parse_cursor(cursor)
    params = {"per_page": "20"}
    if seen.get("since"):
        params["since"] = seen["since"]
    commits = fetch(f"{API}/repos/{owner}/{repo}/commits", params)
    deltas: list[Delta] = []
    newest = seen.get("since", "")
    if not seen and commits:
        first = (commits[0].get("commit", {}).get("message") or "").strip().splitlines()
        deltas.append(
            Delta(summary=s["repo_baseline"].format(msg=first[0][:160] if first else ""),
                  link=commits[0].get("html_url", url), at=time.time())
        )
    if not seen:
        commits = []
    for commit in commits:
        inner = commit.get("commit", {})
        date = (inner.get("author") or {}).get("date", "")
        sha = (commit.get("sha") or "")[:7]
        message = (inner.get("message") or "").strip().splitlines()
        first_line = message[0][:160] if message else ""
        if date and (not newest or date > newest):
            newest = date
        deltas.append(
            Delta(summary=s["new_commit"].format(sha=sha, msg=first_line),
                  quote=first_line, link=commit.get("html_url", url), at=_parse_time(date))
        )
    new_cursor = json.dumps({"since": newest or _now_iso(), "checked": _now_iso()})
    return new_cursor, deltas


def poll_all(mem: Memory, token: str = "", fetch=None, lang: str = "hi") -> PollReport:
    """Poll every watched URL, store deltas, advance cursors. Never raises."""
    fetch = fetch or _fetch
    report = PollReport(checked_at=time.time())
    for watched in mem.list_watched():
        report.checked += 1
        try:
            if watched.kind == "github_issue":
                cursor, deltas = poll_github_issue(watched.url, watched.cursor, token, fetch, lang)
            elif watched.kind == "github_repo":
                cursor, deltas = poll_github_repo(watched.url, watched.cursor, token, fetch, lang)
            else:
                report.errors.append(f"{watched.url}: unsupported kind {watched.kind}")
                continue
        except Exception as exc:  # noqa: BLE001 - one dead source must not stop the rest
            log.warning("poll failed for %s: %s", watched.url, exc)
            report.errors.append(f"{watched.url}: {exc}")
            continue
        mem.update_cursor(watched.id, cursor, report.checked_at)
        if deltas:
            mem.store_changes(
                watched.id, [(d.summary, d.quote, d.link, d.at or report.checked_at) for d in deltas]
            )
            report.new_changes += len(deltas)
    return report


def compose_updates(
    deltas: list[tuple[WatchedItem, list[Change]]], checked_label: str, s: dict | None = None
) -> tuple[str, list[str]]:
    """Spoken delta briefing + screen links (quotes stay on screen too)."""
    s = s or lang_mod.HI
    total = sum(len(changes) for _, changes in deltas)
    links = [c.source_link for _, changes in deltas for c in changes if c.source_link]
    if total == 0:
        return s["updates_none"], []
    firsts = "; ".join(c.summary for _, changes in deltas for c in changes[:3])
    extra = s["updates_extra"].format(n=total - 3) if total > 3 else ""
    return s["updates_some"].format(n=total, label=checked_label, firsts=firsts, extra=extra), links
