"""Live retweet source-ID resolver.

Solves the archive mismatch problem: the ``tweets.js`` archive records
each retweet's wrapper status id (your repost's own id), but the
``DeleteRetweet`` mutation requires the *source* tweet id (the original
post that was retweeted). Fetching live profile timelines and parsing
the GraphQL ``UserTweets`` response is the only reliable way to recover
source ids at scale without copy-pasting URLs.

Flow:
    1. ``UserByScreenName`` -> ``rest_id`` (the user's numeric id).
    2. Paginate ``UserTweets`` with ``cursor`` until the bottom cursor
       stops advancing or we hit ``max_tweets``.
    3. Walk the timeline entries. Every entry whose tweet_results carries
       a ``legacy.retweeted_status_result`` (or whose legacy.full_text
       starts with ``RT @``) is one of *our* retweets -- emit the source
       tweet's ``rest_id``.

Each yielded dict has this shape::

    {
        "id_str": "<source tweet id>",        # ID for DeleteRetweet
        "full_text": "...",
        "wrapper_id": "<our repost id>",      # from tweets.js archive
        "source_user": "handle_of_original",
        "created_at": "...",
        "resolved_via": "live_UserTweets",
    }

All network errors are surfaced as :class:`ResolverError` with enough
context for the CLI to show an actionable message.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Iterator

import requests

from .actions import ActionError, WEB_BEARER
from .discovery import get_query_id


# Feature blobs captured from x.com's live JS bundle (main.f2cf8c9a.js,
# May 2026). If X adds a new required feature we'll start getting a
# ``GRAPHQL_VALIDATION_FAILED`` error -- easy to spot in the response
# body and update below.
_USER_TWEETS_FEATURES: dict[str, bool] = {
    k: True
    for k in (
        "rweb_video_screen_enabled",
        "rweb_cashtags_enabled",
        "profile_label_improvements_pcf_label_in_post_enabled",
        "responsive_web_profile_redirect_enabled",
        "rweb_tipjar_consumption_enabled",
        "verified_phone_label_enabled",
        "creator_subscriptions_tweet_preview_api_enabled",
        "responsive_web_graphql_timeline_navigation_enabled",
        "responsive_web_graphql_skip_user_profile_image_extensions_enabled",
        "premium_content_api_read_enabled",
        "communities_web_enable_tweet_community_results_fetch",
        "c9s_tweet_anatomy_moderator_badge_enabled",
        "responsive_web_grok_analyze_button_fetch_trends_enabled",
        "responsive_web_grok_analyze_post_followups_enabled",
        "rweb_cashtags_composer_attachment_enabled",
        "responsive_web_jetfuel_frame",
        "responsive_web_grok_share_attachment_enabled",
        "responsive_web_grok_annotations_enabled",
        "articles_preview_enabled",
        "responsive_web_edit_tweet_api_enabled",
        "graphql_is_translatable_rweb_tweet_is_translatable_enabled",
        "view_counts_everywhere_api_enabled",
        "longform_notetweets_consumption_enabled",
        "responsive_web_twitter_article_tweet_consumption_enabled",
        "content_disclosure_indicator_enabled",
        "content_disclosure_ai_generated_indicator_enabled",
        "responsive_web_grok_show_grok_translated_post",
        "responsive_web_grok_analysis_button_from_backend",
        "post_ctas_fetch_enabled",
        "freedom_of_speech_not_reach_fetch_enabled",
        "standardized_nudges_misinfo",
        "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled",
        "longform_notetweets_rich_text_read_enabled",
        "longform_notetweets_inline_media_enabled",
        "responsive_web_grok_image_annotation_enabled",
        "responsive_web_grok_imagine_annotation_enabled",
        "responsive_web_grok_community_note_auto_translation_is_enabled",
        "responsive_web_enhance_cards_enabled",
    )
}

_USER_TWEETS_FIELD_TOGGLES: dict[str, bool] = {
    "withPayments": False,
    "withAuxiliaryUserLabels": False,
    "withArticleRichContentState": True,
    "withArticlePlainText": False,
    "withArticleSummaryText": False,
    "withArticleVoiceOver": False,
    "withGrokAnalyze": False,
    "withDisallowedReplyControls": False,
}

_USER_BY_SCREEN_NAME_FEATURES: dict[str, bool] = {
    k: True
    for k in (
        "hidden_profile_subscriptions_enabled",
        "profile_label_improvements_pcf_label_in_post_enabled",
        "responsive_web_profile_redirect_enabled",
        "rweb_tipjar_consumption_enabled",
        "verified_phone_label_enabled",
        "subscriptions_verification_info_is_identity_verified_enabled",
        "subscriptions_verification_info_verified_since_enabled",
        "highlights_tweets_tab_ui_enabled",
        "responsive_web_twitter_article_notes_tab_enabled",
        "subscriptions_feature_can_gift_premium",
        "creator_subscriptions_tweet_preview_api_enabled",
        "responsive_web_graphql_skip_user_profile_image_extensions_enabled",
        "responsive_web_graphql_timeline_navigation_enabled",
    )
}


class ResolverError(Exception):
    """Non-retryable failure while walking the live timeline."""


@dataclass
class ResolveStats:
    pages_fetched: int = 0
    entries_seen: int = 0
    retweets_found: int = 0
    unresolvable: int = 0


def _gql_get(
    session: requests.Session,
    op: str,
    variables: dict,
    features: dict,
    field_toggles: dict | None = None,
    *,
    offline: bool = False,
    timeout: float = 30.0,
) -> dict:
    """Run a GraphQL GET query against x.com's /i/api/graphql."""
    qid = get_query_id(op, offline=offline)
    params = {
        "variables": json.dumps(variables, separators=(",", ":")),
        "features": json.dumps(features, separators=(",", ":")),
    }
    if field_toggles is not None:
        params["fieldToggles"] = json.dumps(field_toggles, separators=(",", ":"))

    url = f"https://x.com/i/api/graphql/{qid}/{op}"
    # ct0 header without tripping over duplicate cookies.
    ct0 = ""
    for c in session.cookies:
        if c.name == "ct0":
            ct0 = c.value or ""
            if c.domain.endswith("x.com"):
                break
    headers = {
        "authorization": f"Bearer {WEB_BEARER}",
        "x-csrf-token": ct0,
        "x-twitter-active-user": "yes",
        "x-twitter-auth-type": "OAuth2Session",
        "x-twitter-client-language": "en",
        "accept": "*/*",
        "accept-language": "en-US,en;q=0.9",
        "referer": "https://x.com/",
        "user-agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
    }

    try:
        req = requests.Request("GET", url, headers=headers, params=params)
        prepped = session.prepare_request(req)
        # Kill content-type/origin the session might have set for mutations.
        for h in ("content-type", "Content-Type", "origin", "Origin"):
            prepped.headers.pop(h, None)
        resp = session.send(prepped, timeout=timeout, allow_redirects=False)
    except requests.RequestException as exc:
        raise ResolverError(f"{op}: network error: {exc}") from exc

    if resp.status_code in (401, 403):
        raise ActionError(
            f"{op}: HTTP {resp.status_code}: authentication rejected. "
            "Refresh your cookies with 'xtool login' and retry."
        )
    if not resp.ok:
        raise ResolverError(
            f"{op}: HTTP {resp.status_code}: {resp.text[:300]}"
        )
    try:
        body = resp.json()
    except ValueError as exc:
        raise ResolverError(
            f"{op}: non-JSON response: {resp.text[:300]}"
        ) from exc
    if body.get("errors"):
        msg = "; ".join(e.get("message", "?") for e in body["errors"])
        raise ResolverError(f"{op}: GraphQL errors: {msg[:300]}")
    return body


def resolve_screen_name(
    session: requests.Session,
    screen_name: str,
    *,
    offline: bool = False,
) -> str:
    """Return the ``rest_id`` (user id) for a ``@handle``."""
    handle = screen_name.lstrip("@")
    body = _gql_get(
        session,
        "UserByScreenName",
        variables={"screen_name": handle, "withSafetyModeUserFields": True},
        features=_USER_BY_SCREEN_NAME_FEATURES,
        field_toggles={"withAuxiliaryUserLabels": False},
        offline=offline,
    )
    try:
        user = body["data"]["user"]["result"]
        rest_id = user.get("rest_id") or user.get("id")
    except (KeyError, TypeError):
        raise ResolverError(
            f"UserByScreenName: no user block in response for @{handle}: "
            f"{str(body)[:200]}"
        )
    if not rest_id:
        raise ResolverError(
            f"UserByScreenName: @{handle} has no rest_id "
            f"(protected/suspended?): {str(body)[:200]}"
        )
    return str(rest_id)


def _extract_retweet(entry: dict) -> dict | None:
    """If this timeline entry is one of our retweets, return the
    normalized dict. Otherwise return None.
    """
    # The timeline entry shape is:
    # entry.content.itemContent.tweet_results.result.{legacy, rest_id}
    content = entry.get("content") or {}
    item = content.get("itemContent") or {}
    tweet_results = item.get("tweet_results") or {}
    result = tweet_results.get("result") or {}
    # "TweetWithVisibilityResults" wraps the actual tweet one level deeper.
    if result.get("__typename") == "TweetWithVisibilityResults":
        result = result.get("tweet") or {}

    legacy = result.get("legacy") or {}
    if not legacy:
        return None

    # A retweet on the profile timeline shows up as: the tweet is the
    # ORIGINAL tweet, but with retweeted_status_result pointing back to
    # itself from the RT wrapper. The robust signal is:
    #   legacy.retweeted_status_result  (a dict)
    # OR:
    #   full_text starts with "RT @" AND retweeted_status_id_str present.
    rt_block = legacy.get("retweeted_status_result") or {}
    rt_result = rt_block.get("result") or {}
    if rt_result.get("__typename") == "TweetWithVisibilityResults":
        rt_result = rt_result.get("tweet") or {}

    source_id = (
        rt_result.get("rest_id")
        or (rt_result.get("legacy") or {}).get("id_str")
        or legacy.get("retweeted_status_id_str")
    )
    if not source_id:
        # Not a retweet.
        return None

    source_legacy = rt_result.get("legacy") or {}
    source_user = None
    # Try to surface the original author's handle for the filter/dry-run
    # banner; this is best-effort.
    try:
        src_core = (rt_result.get("core") or {}).get("user_results") or {}
        src_user = (src_core.get("result") or {}).get("legacy") or {}
        source_user = src_user.get("screen_name")
    except (KeyError, TypeError):
        pass

    return {
        "id_str": str(source_id),
        "full_text": source_legacy.get("full_text") or legacy.get("full_text") or "",
        "wrapper_id": legacy.get("id_str", ""),
        "source_user": source_user,
        "created_at": legacy.get("created_at", ""),
        "resolved_via": "live_UserTweets",
    }


def _walk_entries(
    instructions: list[dict],
) -> Iterator[tuple[dict, str | None]]:
    """Yield ``(entry, bottom_cursor)`` tuples from a UserTweets response.

    The response is a list of instructions of which exactly one is
    ``TimelineAddEntries``. Entries include the tweet rows and two
    cursor entries (top/bottom).
    """
    bottom_cursor: str | None = None
    for instr in instructions:
        if instr.get("type") != "TimelineAddEntries":
            continue
        for entry in instr.get("entries") or []:
            content = entry.get("content") or {}
            entry_type = content.get("entryType") or content.get("__typename")
            if entry_type == "TimelineTimelineCursor" and content.get(
                "cursorType"
            ) == "Bottom":
                bottom_cursor = content.get("value")
                continue
            # "TimelineTimelineItem" is the tweet row we want.
            yield entry, bottom_cursor


def iter_live_retweets(
    session: requests.Session,
    user_id: str,
    *,
    max_tweets: int = 10000,
    page_size: int = 40,
    rate: float = 1.0,
    offline: bool = False,
    on_page: callable | None = None,
) -> Iterator[dict]:
    """Stream retweets from a user's live profile timeline.

    Args:
        max_tweets: stop after walking this many timeline entries total.
        page_size: UserTweets ``count`` variable (X caps at 40).
        rate: pages per second; 1.0 is conservative and safe.
        on_page: callback ``f(stats)`` after each page.
    """
    stats = ResolveStats()
    cursor: str | None = None
    interval = 1.0 / rate if rate > 0 else 0.0
    seen_source: set[str] = set()

    while stats.entries_seen < max_tweets:
        variables: dict[str, Any] = {
            "userId": str(user_id),
            "count": int(page_size),
            "includePromotedContent": False,
            "withQuickPromoteEligibilityTweetFields": False,
            "withVoice": False,
            "withV2Timeline": True,
        }
        if cursor:
            variables["cursor"] = cursor

        body = _gql_get(
            session,
            "UserTweets",
            variables=variables,
            features=_USER_TWEETS_FEATURES,
            field_toggles=_USER_TWEETS_FIELD_TOGGLES,
            offline=offline,
        )
        stats.pages_fetched += 1

        try:
            instructions = (
                body["data"]["user"]["result"]["timeline_v2"]["timeline"][
                    "instructions"
                ]
            )
        except (KeyError, TypeError):
            # Some accounts return timeline instead of timeline_v2.
            try:
                instructions = (
                    body["data"]["user"]["result"]["timeline"]["timeline"][
                        "instructions"
                    ]
                )
            except (KeyError, TypeError):
                raise ResolverError(
                    "UserTweets: unexpected response shape: "
                    f"{str(body)[:300]}"
                )

        new_cursor: str | None = None
        had_entry = False
        for entry, bottom in _walk_entries(instructions):
            had_entry = True
            stats.entries_seen += 1
            if bottom:
                new_cursor = bottom
            rt = _extract_retweet(entry)
            if rt is None:
                continue
            # Dedup on source id in case the user retweeted the same
            # source more than once (rare but possible).
            if rt["id_str"] in seen_source:
                continue
            seen_source.add(rt["id_str"])
            stats.retweets_found += 1
            yield rt

        if on_page:
            on_page(stats)

        # Terminate when the cursor stops advancing or the page had no
        # content at all.
        if not had_entry or not new_cursor or new_cursor == cursor:
            break
        cursor = new_cursor

        if interval:
            time.sleep(interval)
