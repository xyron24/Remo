"""Watcher: URL kinds, cursored polling with fixtures, honest errors."""
import json
from pathlib import Path

from remo import watcher as W
from remo.memory import Memory

ISSUE = {
    "state": "open", "title": "Login bug",
    "html_url": "https://github.com/o/r/issues/214",
}


def _comments(*ids: int) -> list:
    return [
        {"id": i, "body": f"comment body {i}", "user": {"login": f"dev{i}"},
         "created_at": "2026-11-10T10:00:00Z",
         "html_url": f"https://github.com/o/r/issues/214#issuecomment-{i}"}
        for i in ids
    ]


def _issue_fetcher(issue: dict, comments: list):
    def fetch(url: str, params: dict | None = None, token: str = ""):
        if url.endswith("/comments"):
            return comments
        return issue

    return fetch


def test_kind_for_url() -> None:
    assert W.kind_for_url("https://github.com/o/r/issues/214") == "github_issue"
    assert W.kind_for_url("https://github.com/o/r/pull/220") == "github_issue"
    assert W.kind_for_url("https://github.com/o/r") == "github_repo"
    assert W.kind_for_url("https://example.com/x") is None


def test_first_poll_sets_baseline_only() -> None:
    cursor, deltas = W.poll_github_issue(
        "https://github.com/o/r/issues/214", "", fetch=_issue_fetcher(ISSUE, _comments(1, 2))
    )
    assert len(deltas) == 1 and "nazar rahegi" in deltas[0].summary
    assert json.loads(cursor)["last_comment_id"] == 2


def test_second_poll_reports_only_fresh_comments() -> None:
    cursor, _ = W.poll_github_issue(
        "https://github.com/o/r/issues/214", "", fetch=_issue_fetcher(ISSUE, _comments(1, 2))
    )
    cursor2, deltas = W.poll_github_issue(
        "https://github.com/o/r/issues/214", cursor,
        fetch=_issue_fetcher(ISSUE, _comments(1, 2, 3, 4, 5)),
    )
    assert [d.link for d in deltas] == [
        f"https://github.com/o/r/issues/214#issuecomment-{i}" for i in (3, 4, 5)
    ]
    assert all("naya comment" in d.summary for d in deltas)
    assert json.loads(cursor2)["last_comment_id"] == 5


def test_state_change_is_a_delta() -> None:
    cursor, _ = W.poll_github_issue(
        "https://github.com/o/r/issues/214", "", fetch=_issue_fetcher(ISSUE, [])
    )
    closed = dict(ISSUE, state="closed")
    _, deltas = W.poll_github_issue(
        "https://github.com/o/r/issues/214", cursor, fetch=_issue_fetcher(closed, [])
    )
    assert len(deltas) == 1 and "closed" in deltas[0].summary


def test_repo_poll_reports_new_commits() -> None:
    from datetime import datetime, timedelta, timezone

    fresh_date = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()

    def commits(url: str, params: dict | None = None, token: str = ""):
        assert url.endswith("/commits")
        all_commits = [
            {"sha": "abc1234", "commit": {"message": "Fix login", "author": {"date": fresh_date}},
             "html_url": "https://github.com/o/r/commit/abc1234"},
        ]
        since = (params or {}).get("since", "")
        return [c for c in all_commits if c["commit"]["author"]["date"] > since]

    cursor, deltas = W.poll_github_repo("https://github.com/o/r", "", fetch=commits)
    assert len(deltas) == 1 and "nazar shuru" in deltas[0].summary
    cursor2, deltas2 = W.poll_github_repo("https://github.com/o/r", cursor, fetch=commits)
    assert len(deltas2) == 1 and "abc1234" in deltas2[0].summary
    assert json.loads(cursor2)["since"] == fresh_date


def test_poll_all_stores_and_never_raises(tmp_path: Path) -> None:
    mem = Memory(tmp_path / "remo.db")
    mem.watch_url("github_issue", "https://github.com/o/r/issues/214")

    def boom(url: str, params: dict | None = None, token: str = ""):
        raise ConnectionError("offline")

    report = W.poll_all(mem, fetch=boom)
    assert report.checked == 1 and report.new_changes == 0 and len(report.errors) == 1

    report = W.poll_all(mem, fetch=_issue_fetcher(ISSUE, _comments(1)))
    assert report.new_changes == 1 and not report.errors
    assert len(mem.unbriefed_changes()) == 1
    mem.close()


def test_compose_updates_counts_and_links(tmp_path: Path) -> None:
    mem = Memory(tmp_path / "remo.db")
    watched = mem.watch_url("github_issue", "https://github.com/o/r/issues/214")
    mem.store_changes(watched.id, [
        ("Pehla badlaav.", "q1", "https://x/1", 1.0),
        ("Dusra badlaav.", "q2", "https://x/2", 2.0),
        ("Teesra badlaav.", "q3", "https://x/3", 3.0),
    ])
    say, links = W.compose_updates(mem.unbriefed_changes(), "as of 10:00 AM")
    assert say.startswith("3 badlaav") and "Pehla" in say and "as of" in say
    assert links == ["https://x/1", "https://x/2", "https://x/3"]
    mem.close()
