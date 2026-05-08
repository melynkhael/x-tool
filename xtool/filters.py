"""Filter logic for the `xtool filter` subcommand.

All filter functions take a tweet dict (as produced by `parser.iter_tweets`)
and return True if the tweet should be KEPT in the output list (i.e.
eventually deleted).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Optional

from dateutil import parser as dateparser


TweetType = str  # "tweet" | "retweet" | "reply"


def classify(tweet: dict) -> TweetType:
    """Return 'retweet' / 'reply' / 'tweet'."""
    text = tweet.get("full_text") or tweet.get("text") or ""
    if text.startswith("RT @"):
        return "retweet"
    if tweet.get("in_reply_to_status_id_str") or tweet.get("in_reply_to_user_id_str"):
        return "reply"
    return "tweet"


def parse_created_at(tweet: dict) -> Optional[datetime]:
    raw = tweet.get("created_at")
    if not raw:
        return None
    try:
        dt = dateparser.parse(raw)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


@dataclass
class FilterOpts:
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    type: str = "all"  # tweet|retweet|reply|all
    keyword: Optional[re.Pattern] = None
    not_keyword: Optional[re.Pattern] = None
    min_likes: Optional[int] = None
    max_likes: Optional[int] = None
    min_retweets: Optional[int] = None
    max_retweets: Optional[int] = None
    keep_ids: set[str] = field(default_factory=set)

    def keep(self, tweet: dict) -> bool:
        """Return True if the tweet should be included in the output."""
        tid = str(tweet.get("id_str") or tweet.get("id") or "")
        if tid and tid in self.keep_ids:
            return False

        # --- date window ---------------------------------------------------
        if self.date_from or self.date_to:
            created = parse_created_at(tweet)
            if created is None:
                return False
            if self.date_from and created < self.date_from:
                return False
            if self.date_to and created > self.date_to:
                return False

        # --- type ----------------------------------------------------------
        if self.type != "all" and classify(tweet) != self.type:
            return False

        # --- text regex ----------------------------------------------------
        text = tweet.get("full_text") or tweet.get("text") or ""
        if self.keyword and not self.keyword.search(text):
            return False
        if self.not_keyword and self.not_keyword.search(text):
            return False

        # --- engagement ----------------------------------------------------
        likes = _int(tweet.get("favorite_count"))
        rts = _int(tweet.get("retweet_count"))
        if self.min_likes is not None and likes < self.min_likes:
            return False
        if self.max_likes is not None and likes > self.max_likes:
            return False
        if self.min_retweets is not None and rts < self.min_retweets:
            return False
        if self.max_retweets is not None and rts > self.max_retweets:
            return False

        return True


def apply_filter(tweets: Iterable[dict], opts: FilterOpts) -> Iterable[dict]:
    for t in tweets:
        if opts.keep(t):
            yield t


def load_keep_ids(path: Optional[str]) -> set[str]:
    if not path:
        return set()
    ids: set[str] = set()
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#"):
                ids.add(line)
    return ids
