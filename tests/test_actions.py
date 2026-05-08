"""Tests for the generic action runner (no network)."""

from __future__ import annotations

import json
import warnings

import pytest

from xtool.actions import (
    ACTIONS,
    ActionError,
    Credentials,
    bulk_action,
    get_action,
)


DRY_CREDS = Credentials(
    auth_token="a" * 40,
    ct0="b" * 40,
)


def test_action_table_covers_required_ops():
    assert set(ACTIONS) >= {"delete", "unretweet", "unlike"}
    for key, action in ACTIONS.items():
        vars_ = action.build_variables("123")
        assert "123" in json.dumps(vars_), key


def test_credentials_reject_empty():
    with pytest.raises(ValueError):
        Credentials("", "something")
    with pytest.raises(ValueError):
        Credentials("something", "")


def test_credentials_warn_on_short_values():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        Credentials("short", "also_short")
    assert any("suspiciously short" in str(w.message) for w in caught)


def test_credentials_from_file_bad_json(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("not json", encoding="utf-8")
    with pytest.raises(ValueError, match="cannot read credentials"):
        Credentials.from_file(p)


def test_credentials_from_file_missing_key(tmp_path):
    p = tmp_path / "half.json"
    p.write_text(json.dumps({"auth_token": "aaaaaaaaaaaaaaaaaaaaaaaa"}), encoding="utf-8")
    with pytest.raises(ValueError, match="missing required key"):
        Credentials.from_file(p)


def test_bulk_action_dry_run_logs_action_field(tmp_path):
    log = tmp_path / "log.jsonl"
    stats = bulk_action(
        ["111", "222"], DRY_CREDS, get_action("unretweet"),
        dry_run=True, log_path=log, resume=True, rate=0,
    )
    assert stats.attempted == 2
    assert stats.failed == 0
    lines = [json.loads(l) for l in log.read_text().splitlines() if l.strip()]
    assert [r["action"] for r in lines] == ["unretweet", "unretweet"]


def test_bulk_action_resume_is_scoped_per_action(tmp_path):
    log = tmp_path / "log.jsonl"
    bulk_action(
        ["111"], DRY_CREDS, get_action("unretweet"),
        dry_run=True, log_path=log, resume=True, rate=0,
    )
    stats = bulk_action(
        ["111"], DRY_CREDS, get_action("delete"),
        dry_run=True, log_path=log, resume=True, rate=0,
    )
    assert stats.attempted == 1
    assert stats.skipped == 0


def test_bulk_action_dedupes_within_run(tmp_path):
    log = tmp_path / "log.jsonl"
    stats = bulk_action(
        ["111", "222", "111", "333", "222"], DRY_CREDS, get_action("delete"),
        dry_run=True, log_path=log, resume=False, rate=0,
    )
    assert stats.attempted == 3  # 111, 222, 333 - each processed once
    lines = [json.loads(l) for l in log.read_text().splitlines() if l.strip()]
    assert [r["id"] for r in lines] == ["111", "222", "333"]


def test_legacy_deleter_still_works(tmp_path):
    from xtool.deleter import bulk_delete

    log = tmp_path / "deleted.jsonl"
    stats = bulk_delete(
        ["555"], DRY_CREDS,
        dry_run=True, log_path=log, resume=True, rate=0,
    )
    assert stats.deleted == 0
    assert stats.attempted == 1


def test_bulk_action_auth_failed_aborts(tmp_path, monkeypatch):
    """An auth_failed outcome must raise ActionError instead of
    silently failing every id in the list."""
    log = tmp_path / "log.jsonl"

    # Monkeypatch _attempt to simulate bad credentials.
    from xtool import actions as actions_mod

    def fake_attempt(*_a, **_kw):
        return "auth_failed", "HTTP 401: Could not authenticate you"

    monkeypatch.setattr(actions_mod, "_attempt", fake_attempt)

    with pytest.raises(ActionError, match="authentication rejected"):
        bulk_action(
            ["111", "222", "333"], DRY_CREDS, get_action("delete"),
            dry_run=False, log_path=log, resume=False, rate=0,
        )
    # Only the first id should have been attempted + logged.
    lines = [json.loads(l) for l in log.read_text().splitlines() if l.strip()]
    assert len(lines) == 1
    assert lines[0]["outcome"] == "auth_failed"
    # New: the error detail must be present in the log.
    assert "Could not authenticate you" in lines[0]["error"]


def test_bulk_action_records_error_detail(tmp_path, monkeypatch):
    """A normal 'failed' outcome must record the error body in the log."""
    log = tmp_path / "log.jsonl"
    from xtool import actions as actions_mod

    def fake_attempt(*_a, **_kw):
        return "failed", 'HTTP 422: {"errors":[{"message":"bad request"}]}'

    monkeypatch.setattr(actions_mod, "_attempt", fake_attempt)

    stats = bulk_action(
        ["111"], DRY_CREDS, get_action("unretweet"),
        dry_run=False, log_path=log, resume=False, rate=0,
    )
    assert stats.failed == 1
    lines = [json.loads(l) for l in log.read_text().splitlines() if l.strip()]
    assert lines[0]["outcome"] == "failed"
    assert "HTTP 422" in lines[0]["error"]
    assert "bad request" in lines[0]["error"]


def test_unretweet_action_uses_DeleteRetweet():
    """Regression: live X web client uses DeleteRetweet, not UnretweetTweet."""
    action = get_action("unretweet")
    assert action.name == "DeleteRetweet", (
        "unretweet must call the DeleteRetweet GraphQL operation; "
        "UnretweetTweet was retired by X and returns HTTP 422."
    )
    assert action.build_variables("123") == {
        "source_tweet_id": "123",
        "dark_request": False,
    }
