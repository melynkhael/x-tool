"""Tests for like.js parsing."""

from __future__ import annotations

from pathlib import Path

from xtool.parser import iter_likes


FIXTURE = Path(__file__).parent.parent / "examples" / "likes.sample.js"


def test_iter_likes_reads_fixture():
    likes = list(iter_likes(FIXTURE))
    assert len(likes) == 2
    assert {l["id_str"] for l in likes} == {
        "2000000000000000001",
        "2000000000000000002",
    }
    # Original fields survive.
    assert likes[0]["fullText"].startswith("A liked tweet")
