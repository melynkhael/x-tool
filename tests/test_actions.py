"""Tests for the generic action runner (no network)."""

from __future__ import annotations

import json

import pytest

from xtool.actions import ACTIONS, Credentials, bulk_action, get_action


def test_action_table_covers_required_ops():
    assert set(ACTIONS) >= {"delete", "unretweet", "unlike"}
    # Each action must produce variables that include the id.
    for key, action in ACTIONS.items():
        vars_ = action.build_variables("123")
        assert "123" in json.dumps(vars_), key


def test_bulk_action_dry_run_logs_action_field(tmp_path):
    log = tmp_path / "log.jsonl"
    action = get_action("unretweet")
    creds = Credentials("dry", "dry")
    stats = bulk_action(
        ["111", "222"], creds, action,
        dry_run=True, log_path=log, resume=True, rate=0,
    )
    assert stats.attempted == 2
    assert stats.failed == 0
    lines = [json.loads(l) for l in log.read_text().splitlines() if l.strip()]
    assert [r["action"] for r in lines] == ["unretweet", "unretweet"]


def test_bulk_action_resume_is_scoped_per_action(tmp_path):
    log = tmp_path / "log.jsonl"
    creds = Credentials("dry", "dry")
    # First, record an "unretweet" of id 111.
    bulk_action(
        ["111"], creds, get_action("unretweet"),
        dry_run=True, log_path=log, resume=True, rate=0,
    )
    # A later "delete" of the same id must NOT be skipped.
    stats = bulk_action(
        ["111"], creds, get_action("delete"),
        dry_run=True, log_path=log, resume=True, rate=0,
    )
    assert stats.attempted == 1
    assert stats.skipped == 0


def test_legacy_deleter_still_works(tmp_path):
    """Old callers that import from xtool.deleter keep working."""
    from xtool.deleter import bulk_delete

    log = tmp_path / "deleted.jsonl"
    stats = bulk_delete(
        ["555"], Credentials("dry", "dry"),
        dry_run=True, log_path=log, resume=True, rate=0,
    )
    # Legacy attribute name is still readable.
    assert stats.deleted == 0
    assert stats.attempted == 1
