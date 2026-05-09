"""Tests for the live-timeline resolver (pure parsing, no network)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from xtool import resolver
from xtool.resolver import (
    ResolveStats,
    _extract_retweet,
    _find_bottom_cursor,
    _iter_tweet_items,
    iter_live_retweets,
)


# --- builders -----------------------------------------------------------

def _tweet_item_entry(tweet_result: dict, entry_id: str = "tweet-1") -> dict:
    """Top-level TimelineTimelineItem entry."""
    return {
        "entryId": entry_id,
        "content": {
            "entryType": "TimelineTimelineItem",
            "itemContent": {
                "itemType": "TimelineTweet",
                "tweet_results": {"result": tweet_result},
            },
        },
    }


def _tweet_item_with_social_context(
    tweet_result: dict,
    *,
    context_type: str = "SocialContextSelfRepost",
    context_type_value: str | None = None,
    entry_id: str = "tweet-sr-1",
) -> dict:
    sc: dict = {"type": context_type, "text": "You reposted"}
    if context_type_value is not None:
        sc["contextType"] = context_type_value
    return {
        "entryId": entry_id,
        "content": {
            "entryType": "TimelineTimelineItem",
            "itemContent": {
                "itemType": "TimelineTweet",
                "tweet_results": {"result": tweet_result},
                "socialContext": sc,
            },
        },
    }


def _module_entry(items: list[dict], entry_id: str = "profile-module-0") -> dict:
    return {
        "entryId": entry_id,
        "content": {
            "entryType": "TimelineTimelineModule",
            "items": [
                {
                    "entryId": f"{entry_id}-{i}",
                    "item": {
                        "itemContent": {
                            "itemType": "TimelineTweet",
                            "tweet_results": {"result": result},
                        }
                    },
                }
                for i, result in enumerate(items)
            ],
        },
    }


def _cursor_entry(value: str, cursor_type: str = "Bottom") -> dict:
    return {
        "entryId": f"cursor-{cursor_type.lower()}",
        "content": {
            "entryType": "TimelineTimelineCursor",
            "cursorType": cursor_type,
            "value": value,
        },
    }


def _make_tweet(
    rest_id: str,
    *,
    full_text: str = "hello",
    user_screen_name: str = "me",
    retweeted_status: dict | None = None,
    retweeted: bool = False,
    retweeted_status_id_str: str | None = None,
) -> dict:
    legacy: dict = {
        "id_str": rest_id,
        "full_text": full_text,
        "created_at": "Wed Jan 01 00:00:00 +0000 2024",
    }
    if retweeted:
        legacy["retweeted"] = True
    if retweeted_status_id_str:
        legacy["retweeted_status_id_str"] = retweeted_status_id_str
    if retweeted_status:
        legacy["retweeted_status_result"] = {"result": retweeted_status}
    return {
        "__typename": "Tweet",
        "rest_id": rest_id,
        "legacy": legacy,
        "core": {
            "user_results": {
                "result": {"legacy": {"screen_name": user_screen_name}}
            }
        },
    }


# --- extraction --------------------------------------------------------

def test_extract_signal_a_retweeted_status_result():
    source = _make_tweet("SRC1", user_screen_name="orig_author", full_text="original!")
    wrapper = _make_tweet(
        "WRAPPER1",
        full_text="RT @orig_author: original!",
        retweeted_status=source,
    )
    entry = _tweet_item_entry(wrapper)
    rt = _extract_retweet(entry)
    assert rt is not None
    assert rt["id_str"] == "SRC1"
    assert rt["wrapper_id"] == "WRAPPER1"
    assert rt["source_user"] == "orig_author"
    assert rt["full_text"] == "original!"


def test_extract_signal_a_through_visibility_wrapper():
    source = _make_tweet("SRC2", user_screen_name="orig")
    wrapper = _make_tweet("WRAPPER2", retweeted_status=source)
    # Wrap the outer tweet in TweetWithVisibilityResults.
    outer = {
        "__typename": "TweetWithVisibilityResults",
        "tweet": wrapper,
    }
    entry = _tweet_item_entry(outer)
    rt = _extract_retweet(entry)
    assert rt is not None and rt["id_str"] == "SRC2"


def test_extract_signal_b_social_context_self_repost():
    """Profile timeline with 'You reposted' / 'Anda memposting ulang'
    on an ORIGINAL tweet -- source id is the tweet itself."""
    source = _make_tweet("COBAK1", user_screen_name="CobakOfficial", full_text="a repost")
    entry = _tweet_item_with_social_context(
        source, context_type="SocialContextSelfRepost"
    )
    rt = _extract_retweet(entry)
    assert rt is not None
    assert rt["id_str"] == "COBAK1"
    assert rt["source_user"] == "CobakOfficial"


def test_extract_signal_b_timeline_general_context_repost():
    source = _make_tweet("GRND1", user_screen_name="Grindery")
    entry = _tweet_item_with_social_context(
        source,
        context_type="TimelineGeneralContext",
        context_type_value="SelfRepost",
    )
    rt = _extract_retweet(entry)
    assert rt is not None and rt["id_str"] == "GRND1"


def test_extract_signal_c_legacy_retweeted_flag():
    tw = _make_tweet(
        "OLD1",
        full_text="RT @someone: legacy classic",
        retweeted=True,
        retweeted_status_id_str="SRC_OLD_1",
    )
    entry = _tweet_item_entry(tw)
    rt = _extract_retweet(entry)
    assert rt is not None
    assert rt["id_str"] == "SRC_OLD_1"


def test_extract_returns_none_for_original_non_repost():
    tw = _make_tweet("SELF1", user_screen_name="me", full_text="just my own tweet")
    # No socialContext, no retweeted flag, no RT prefix.
    entry = _tweet_item_entry(tw)
    assert _extract_retweet(entry) is None


def test_extract_ignores_generic_context_without_repost_marker():
    """A TimelineGeneralContext with a contextType that is NOT a repost
    marker (e.g. pinned) must not be treated as a repost."""
    tw = _make_tweet("PIN1", user_screen_name="me")
    entry = _tweet_item_with_social_context(
        tw,
        context_type="TimelineGeneralContext",
        context_type_value="Pinned",
    )
    assert _extract_retweet(entry) is None


# --- module / item iteration ------------------------------------------

def test_iter_tweet_items_walks_modules():
    """Module entries expose their sub-items."""
    src_a = _make_tweet("SRC_A", user_screen_name="A")
    src_b = _make_tweet("SRC_B", user_screen_name="B")
    mod_entry = _module_entry([src_a, src_b])
    instructions = [{"type": "TimelineAddEntries", "entries": [mod_entry]}]
    items = list(_iter_tweet_items(instructions))
    assert len(items) == 2


def test_iter_tweet_items_mixes_top_level_and_modules():
    src = _make_tweet("SRC_TOP")
    top = _tweet_item_entry(src, entry_id="top-1")
    mod = _module_entry([_make_tweet("SRC_M1"), _make_tweet("SRC_M2")])
    instructions = [
        {"type": "TimelineAddEntries", "entries": [top, mod]},
    ]
    items = list(_iter_tweet_items(instructions))
    assert len(items) == 3


def test_iter_tweet_items_handles_add_to_module_instruction():
    """Page 2+ can deliver extra module items via TimelineAddToModule."""
    module_item = {
        "entryId": "extra-1",
        "item": {
            "itemContent": {
                "itemType": "TimelineTweet",
                "tweet_results": {"result": _make_tweet("SRC_EXTRA")},
            }
        },
    }
    instructions = [
        {"type": "TimelineAddToModule", "moduleItems": [module_item]}
    ]
    items = list(_iter_tweet_items(instructions))
    assert len(items) == 1


# --- cursor discovery --------------------------------------------------

def test_find_bottom_cursor_in_add_entries():
    instructions = [
        {
            "type": "TimelineAddEntries",
            "entries": [
                _tweet_item_entry(_make_tweet("1")),
                _cursor_entry("CURSOR_BOT"),
            ],
        }
    ]
    assert _find_bottom_cursor(instructions) == "CURSOR_BOT"


def test_find_bottom_cursor_in_replace_entry():
    """Pages after the first often deliver the bottom cursor via a
    TimelineReplaceEntry instruction instead of TimelineAddEntries."""
    instructions = [
        {
            "type": "TimelineAddEntries",
            "entries": [_tweet_item_entry(_make_tweet("1"))],
        },
        {
            "type": "TimelineReplaceEntry",
            "entry_id_to_replace": "cursor-bottom",
            "entry": {
                "entryId": "cursor-bottom",
                "content": {
                    "entryType": "TimelineTimelineCursor",
                    "cursorType": "Bottom",
                    "value": "CURSOR_NEXT",
                },
            },
        },
    ]
    assert _find_bottom_cursor(instructions) == "CURSOR_NEXT"


def test_find_bottom_cursor_inside_module():
    """Some older profile pagination nests the cursor inside the module's
    own items list instead of at the instruction top-level."""
    module_entry = {
        "entryId": "profile-module-0",
        "content": {
            "entryType": "TimelineTimelineModule",
            "items": [
                {
                    "entryId": "inner-tweet",
                    "item": {
                        "itemContent": {
                            "itemType": "TimelineTweet",
                            "tweet_results": {"result": _make_tweet("X1")},
                        }
                    },
                },
                {
                    "entryId": "inner-cursor",
                    "item": {
                        "itemContent": {
                            "itemType": "TimelineTimelineCursor",
                            "cursorType": "Bottom",
                            "value": "CURSOR_MOD",
                        }
                    },
                },
            ],
        },
    }
    instructions = [
        {"type": "TimelineAddEntries", "entries": [module_entry]}
    ]
    assert _find_bottom_cursor(instructions) == "CURSOR_MOD"


# --- end-to-end iter_live_retweets -------------------------------------

def _fake_response(*pages: list[dict]) -> callable:
    """Build a fake _gql_get that returns successive UserTweets
    responses, one per page."""
    it = iter(pages)

    def _fake(session, op, variables, features, field_toggles=None, **kw):
        if op == "UserByScreenName":
            return {
                "data": {
                    "user": {"result": {"rest_id": "99", "id": "99"}}
                }
            }
        instructions = next(it)
        return {
            "data": {
                "user": {
                    "result": {
                        "timeline_v2": {
                            "timeline": {"instructions": instructions}
                        }
                    }
                }
            }
        }

    return _fake


def test_iter_live_retweets_paginates_until_cursor_stops(monkeypatch):
    """Page 1 returns one retweet + cursor A.
    Page 2 returns two reposts (one via module, one via social-context)
    + cursor B.
    Page 3 returns no new cursor -> pagination stops.
    """
    src1 = _make_tweet("S1", user_screen_name="u1")
    rt1 = _make_tweet("R1", retweeted_status=src1)

    src2 = _make_tweet("S2", user_screen_name="u2")
    rt2 = _make_tweet("R2", retweeted_status=src2)

    src3 = _make_tweet("S3", user_screen_name="CobakOfficial")

    page1 = [
        {
            "type": "TimelineAddEntries",
            "entries": [
                _tweet_item_entry(rt1, entry_id="e1"),
                _cursor_entry("CUR_A"),
            ],
        }
    ]
    page2 = [
        {
            "type": "TimelineAddEntries",
            "entries": [
                _module_entry([rt2], entry_id="mod-1"),
                _tweet_item_with_social_context(src3, entry_id="e-sr"),
            ],
        },
        {
            "type": "TimelineReplaceEntry",
            "entry": {
                "entryId": "cursor-bottom",
                "content": {
                    "entryType": "TimelineTimelineCursor",
                    "cursorType": "Bottom",
                    "value": "CUR_B",
                },
            },
        },
    ]
    # Page 3: entries exist but cursor does not advance -> we stop.
    page3 = [
        {
            "type": "TimelineAddEntries",
            "entries": [_tweet_item_entry(_make_tweet("ORIG1"))],
        }
    ]

    monkeypatch.setattr(
        resolver, "_gql_get", _fake_response(page1, page2, page3)
    )

    results = list(
        iter_live_retweets(
            session=SimpleNamespace(cookies=[]),
            user_id="99",
            rate=0,
            offline=True,
        )
    )
    ids = [r["id_str"] for r in results]
    # Expect: S1 (signal A), S2 (signal A via module), S3 (signal B).
    assert ids == ["S1", "S2", "S3"]


def test_iter_live_retweets_does_not_stop_at_two_entries(monkeypatch):
    """Regression: with a module of 5 items on page 1, we must NOT stop
    after only 2 entries seen (the old bug)."""
    entries = [
        _module_entry(
            [_make_tweet(f"M{i}") for i in range(5)], entry_id="mod-big"
        ),
        _cursor_entry("CUR_X"),
    ]
    page1 = [{"type": "TimelineAddEntries", "entries": entries}]
    # Page 2: same cursor returned -> natural termination.
    page2 = [
        {
            "type": "TimelineAddEntries",
            "entries": [_cursor_entry("CUR_X")],
        }
    ]
    monkeypatch.setattr(
        resolver, "_gql_get", _fake_response(page1, page2)
    )
    # Collect stats via on_page callback.
    page_stats: list[ResolveStats] = []
    list(
        iter_live_retweets(
            session=SimpleNamespace(cookies=[]),
            user_id="99",
            rate=0,
            offline=True,
            on_page=lambda s: page_stats.append(
                ResolveStats(
                    pages_fetched=s.pages_fetched,
                    entries_seen=s.entries_seen,
                    retweets_found=s.retweets_found,
                )
            ),
        )
    )
    # Page 1 must report all 5 module items (NOT 2) as entries_seen.
    assert page_stats[0].entries_seen == 5


def test_iter_live_retweets_debug_dump(monkeypatch, tmp_path):
    """--debug dump fires when entries_seen > 0 but retweets_found == 0."""
    only_originals = [
        {
            "type": "TimelineAddEntries",
            "entries": [
                _tweet_item_entry(_make_tweet("O1"), entry_id="e1"),
                _tweet_item_entry(_make_tweet("O2"), entry_id="e2"),
                _cursor_entry("CUR_END"),
            ],
        }
    ]
    # Page 2: same cursor -> stop.
    page2 = [
        {
            "type": "TimelineAddEntries",
            "entries": [_cursor_entry("CUR_END")],
        }
    ]
    monkeypatch.setattr(
        resolver, "_gql_get", _fake_response(only_originals, page2)
    )
    dbg = tmp_path / "dump.jsonl"
    out = list(
        iter_live_retweets(
            session=SimpleNamespace(cookies=[]),
            user_id="99",
            rate=0,
            offline=True,
            debug_path=dbg,
        )
    )
    assert out == []
    assert dbg.exists() and dbg.stat().st_size > 0
    dumped = [json.loads(l) for l in dbg.read_text().splitlines() if l.strip()]
    # One dump entry for the page that had entries but no retweets.
    assert len(dumped) == 1
    assert dumped[0]["entries_on_page"] == 2
    assert dumped[0]["page"] == 1
