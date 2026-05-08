"""Smoke tests: parse -> filter -> count, no network."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from xtool.filters import FilterOpts, apply_filter, classify, parse_created_at
from xtool.parser import iter_tweets, read_jsonl, write_jsonl


FIXTURE = Path(__file__).parent.parent / "examples" / "tweets.sample.js"


def test_parse_fixture():
    tweets = list(iter_tweets(FIXTURE))
    assert len(tweets) == 4
    assert tweets[0]["id_str"] == "1000000000000000001"


def test_classify():
    tweets = list(iter_tweets(FIXTURE))
    kinds = [classify(t) for t in tweets]
    assert kinds == ["tweet", "retweet", "reply", "tweet"]


def test_filter_max_likes(tmp_path):
    jsonl = tmp_path / "all.jsonl"
    write_jsonl(iter_tweets(FIXTURE), jsonl)
    opts = FilterOpts(max_likes=5)
    kept = list(apply_filter(read_jsonl(jsonl), opts))
    ids = {t["id_str"] for t in kept}
    assert ids == {
        "1000000000000000001",
        "1000000000000000002",
        "1000000000000000003",
    }


def test_filter_date_range(tmp_path):
    jsonl = tmp_path / "all.jsonl"
    write_jsonl(iter_tweets(FIXTURE), jsonl)
    opts = FilterOpts(
        date_to=datetime(2020, 1, 1, tzinfo=timezone.utc),
        type="tweet",
    )
    kept = list(apply_filter(read_jsonl(jsonl), opts))
    assert [t["id_str"] for t in kept] == ["1000000000000000001"]


def test_filter_keyword(tmp_path):
    jsonl = tmp_path / "all.jsonl"
    write_jsonl(iter_tweets(FIXTURE), jsonl)
    opts = FilterOpts(keyword=re.compile("python", re.IGNORECASE))
    kept = list(apply_filter(read_jsonl(jsonl), opts))
    assert [t["id_str"] for t in kept] == ["1000000000000000004"]


def test_parse_created_at():
    tweets = list(iter_tweets(FIXTURE))
    dt = parse_created_at(tweets[0])
    assert dt is not None and dt.year == 2017
