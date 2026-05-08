"""Tests for xtool.discovery - query-id extraction and caching."""

from __future__ import annotations

import json
import time

import pytest

from xtool import discovery
from xtool.discovery import (
    FALLBACK_QUERY_IDS,
    discover_query_ids,
    extract_query_ids,
)


# Representative snippet mimicking the shape of x.com's JS bundle.
SAMPLE_JS = """
!function(e){...}({
    queryId:"AbCdEf1234567890",operationName:"DeleteTweet",
    operationType:"mutation",metadata:{featureSwitches:[]}
},{
    operationName:"UnretweetTweet",queryId:"ZyXwVu0987654321",
    operationType:"mutation"
},{
    queryId:"QqWwEeRrTtYy9999",operationName:"UnfavoriteTweet"
},{
    queryId:"IgnoreMe0000",operationName:"UserByScreenName",operationType:"query"
})
"""


def test_extract_handles_both_orders():
    got = extract_query_ids(SAMPLE_JS)
    assert got["DeleteTweet"] == "AbCdEf1234567890"
    assert got["UnretweetTweet"] == "ZyXwVu0987654321"
    assert got["UnfavoriteTweet"] == "QqWwEeRrTtYy9999"
    # Non-mutation operations also get extracted - that's fine.
    assert got["UserByScreenName"] == "IgnoreMe0000"


def test_extract_is_robust_to_minified_code():
    minified = (
        'A({queryId:"aaaaaaaaaa",operationName:"DeleteTweet"}),'
        'B({operationName:"UnretweetTweet",queryId:"bbbbbbbbbb"})'
    )
    got = extract_query_ids(minified)
    assert got == {"DeleteTweet": "aaaaaaaaaa", "UnretweetTweet": "bbbbbbbbbb"}


def test_offline_fresh_cache_wins(tmp_path, monkeypatch):
    cache = tmp_path / "query_ids.json"
    cache.write_text(
        json.dumps(
            {
                "fetched_at": time.time(),
                "ids": {"DeleteTweet": "cachedDeleteId1"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(discovery, "CACHE_PATH", cache)
    out = discover_query_ids(offline=True)
    assert out["DeleteTweet"] == "cachedDeleteId1"
    # Operations missing from cache must fall through to fallback.
    assert out["UnretweetTweet"] == FALLBACK_QUERY_IDS["UnretweetTweet"]


def test_offline_no_cache_uses_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(discovery, "CACHE_PATH", tmp_path / "missing.json")
    out = discover_query_ids(offline=True)
    for op, qid in FALLBACK_QUERY_IDS.items():
        assert out[op] == qid


def test_get_query_id_env_override(monkeypatch, tmp_path):
    monkeypatch.setattr(discovery, "CACHE_PATH", tmp_path / "q.json")
    monkeypatch.setenv("XTOOL_DELETE_TWEET_QUERY_ID", "envOverride1234")
    assert discovery.get_query_id("DeleteTweet", offline=True) == "envOverride1234"


def test_stale_cache_is_refreshed(tmp_path, monkeypatch):
    cache = tmp_path / "q.json"
    cache.write_text(
        json.dumps(
            {
                "fetched_at": time.time() - 10 * 24 * 3600,  # 10 days old
                "ids": {"DeleteTweet": "staleId"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(discovery, "CACHE_PATH", cache)

    # Block the network and verify we fall back without crashing.
    def boom(*_a, **_kw):
        raise discovery.requests.RequestException("no net in tests")

    monkeypatch.setattr(discovery, "_discover_uncached", boom)
    out = discover_query_ids()
    # Stale cache plus failed fetch -> we end up with fallbacks.
    assert out["DeleteTweet"] == FALLBACK_QUERY_IDS["DeleteTweet"]



def test_discover_with_sources_labels(tmp_path, monkeypatch):
    """Every returned entry is tagged live / cache / fallback correctly."""
    from xtool.discovery import discover_with_sources

    cache = tmp_path / "q.json"
    cache.write_text(
        json.dumps(
            {
                "fetched_at": time.time(),
                "ids": {
                    "DeleteTweet": "cachedDelete1234",
                    # Override a fallback entry with a cached value.
                    "UnretweetTweet": FALLBACK_QUERY_IDS["UnretweetTweet"],
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(discovery, "CACHE_PATH", cache)
    out = discover_with_sources(offline=True)
    # DeleteTweet came from cache (different from fallback).
    assert out["DeleteTweet"] == ("cachedDelete1234", "cache")
    # UnretweetTweet came from cache even though the id matches fallback -
    # the source label is about provenance, not the value.
    assert out["UnretweetTweet"][1] == "cache"
    # An op present only in FALLBACK_QUERY_IDS reports 'fallback'.
    assert out["UnfavoriteTweet"][1] == "fallback"


def test_discover_survives_generic_exception(tmp_path, monkeypatch):
    """A non-RequestException from the scraper must not crash discovery."""
    monkeypatch.setattr(discovery, "CACHE_PATH", tmp_path / "q.json")

    def kaboom(*_a, **_kw):
        raise RuntimeError("unexpected parse failure")

    monkeypatch.setattr(discovery, "_discover_uncached", kaboom)
    out = discover_query_ids()
    # We still get a usable table (fallbacks).
    assert out["DeleteTweet"] == FALLBACK_QUERY_IDS["DeleteTweet"]
