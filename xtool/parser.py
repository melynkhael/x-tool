"""Parser for the X/Twitter archive `tweet.js` / `tweets.js` file.

The archive file is a tiny JavaScript stub that assigns a JSON array to a
global variable, e.g.::

    window.YTD.tweets.part0 = [
      { "tweet" : { "id_str": "123...", "full_text": "...", ... } },
      ...
    ]

We strip the `window.YTD.* = ` prefix, parse the remainder as JSON, and
flatten the `{ "tweet": {...} }` wrapper that newer archives use.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable, Iterator

# Matches `window.YTD.tweets.part0 = `, `window.YTD.tweet.part0 = `, etc.
_PREFIX_RE = re.compile(r"^\s*window\.YTD\.[\w.]+\s*=\s*", re.MULTILINE)


def iter_tweets(path: str | Path) -> Iterator[dict]:
    """Yield each tweet dict from an archive `tweet.js` / `tweets.js` file.

    Supports both the older `{ "id_str": ... }` flat format and the newer
    `{ "tweet": { "id_str": ... } }` nested format.
    """

    raw = Path(path).read_text(encoding="utf-8")
    stripped = _PREFIX_RE.sub("", raw, count=1).strip()
    if not stripped:
        return
    data = json.loads(stripped)
    if not isinstance(data, list):
        raise ValueError(
            f"{path}: expected a JSON array after the assignment, got "
            f"{type(data).__name__}"
        )
    for entry in data:
        if isinstance(entry, dict) and "tweet" in entry and isinstance(entry["tweet"], dict):
            yield entry["tweet"]
        elif isinstance(entry, dict):
            yield entry
        else:
            # Skip anything weird silently; the archive sometimes has
            # blank trailing entries.
            continue


def write_jsonl(tweets: Iterable[dict], out_path: str | Path) -> int:
    """Write tweets as JSON-lines. Returns count written."""
    count = 0
    with Path(out_path).open("w", encoding="utf-8") as fh:
        for t in tweets:
            fh.write(json.dumps(t, ensure_ascii=False))
            fh.write("\n")
            count += 1
    return count


def read_jsonl(path: str | Path) -> Iterator[dict]:
    """Read a JSON-lines file of tweets."""
    with Path(path).open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def iter_likes(path: str | Path) -> Iterator[dict]:
    """Yield each like dict from an archive ``like.js`` file.

    Entries look like::

        { "like": { "tweetId": "123...",
                    "fullText": "...",
                    "expandedUrl": "https://twitter.com/i/web/status/123..." } }

    Older archives may have flat ``{ "tweetId": ... }`` entries; we
    support both and always produce a dict with ``id_str`` plus any
    remaining fields, so downstream code (stats/filter) works the same
    as for tweets.
    """
    raw = Path(path).read_text(encoding="utf-8")
    stripped = _PREFIX_RE.sub("", raw, count=1).strip()
    if not stripped:
        return
    data = json.loads(stripped)
    if not isinstance(data, list):
        raise ValueError(
            f"{path}: expected JSON array after assignment, got "
            f"{type(data).__name__}"
        )
    for entry in data:
        if isinstance(entry, dict) and "like" in entry and isinstance(entry["like"], dict):
            like = dict(entry["like"])
        elif isinstance(entry, dict):
            like = dict(entry)
        else:
            continue
        # Normalize: expose the id under id_str so parser/filter/delete
        # paths can stay uniform with tweets.
        tid = like.get("tweetId") or like.get("id_str") or like.get("id")
        if not tid:
            continue
        like.setdefault("id_str", str(tid))
        yield like
