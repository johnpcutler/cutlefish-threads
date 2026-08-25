#!/usr/bin/env python3
"""Build a static subset site from a local Twitter archive."""

from __future__ import annotations

import argparse
import json
import re
import shutil
from collections import defaultdict
from datetime import datetime
from pathlib import Path

SELF_ID = "533409964"
HANDLE = "johncutlefish"
TWEET_RE = re.compile(r"https://t\.co/\w+")


def load_part(path: Path, part: str) -> list:
    raw = path.read_text(encoding="utf-8")
    prefix = f"window.YTD.tweets.{part} = "
    if raw.startswith(prefix):
        raw = raw[len(prefix) :]
    raw = raw.rstrip()
    if raw.endswith(";"):
        raw = raw[:-1]
    return json.loads(raw)


def parse_created(value: str) -> datetime:
    return datetime.strptime(value, "%a %b %d %H:%M:%S %z %Y")


def expand_text(tweet: dict) -> str:
    text = tweet.get("full_text") or ""
    replacements: list[tuple[str, str]] = []
    entities = tweet.get("entities") or {}
    for url in entities.get("urls") or []:
        short = url.get("url")
        expanded = url.get("expanded_url") or url.get("display_url") or short
        if short and expanded:
            replacements.append((short, expanded))
    media = (tweet.get("extended_entities") or {}).get("media") or entities.get("media") or []
    for item in media:
        short = item.get("url")
        if short:
            replacements.append((short, ""))
    for short, expanded in replacements:
        text = text.replace(short, expanded)
    text = TWEET_RE.sub("", text)
    return re.sub(r"[ \t]+\n", "\n", text).strip()


def excerpt(text: str, limit: int = 140) -> str:
    collapsed = re.sub(r"\s+", " ", text).strip()
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1].rstrip() + "…"


def media_names(tweet_id: str, media_dir: Path) -> list[str]:
    return sorted(p.name for p in media_dir.glob(f"{tweet_id}-*"))


def serialize_tweet(tweet: dict, media_dir: Path) -> dict:
    created = parse_created(tweet["created_at"])
    names = media_names(tweet["id_str"], media_dir)
    return {
        "id": tweet["id_str"],
        "date": created.strftime("%Y-%m-%d"),
        "datetime": created.isoformat(),
        "likes": int(tweet.get("favorite_count") or 0),
        "rts": int(tweet.get("retweet_count") or 0),
        "text": expand_text(tweet),
        "media": [f"media/{name}" for name in names],
    }


def load_tweets(archive: Path) -> list[dict]:
    wraps = load_part(archive / "tweets.js", "part0")
    wraps += load_part(archive / "tweets-part1.js", "part1")
    tweets = []
    for wrap in wraps:
        tweet = wrap["tweet"]
        text = tweet.get("full_text") or ""
        if text.startswith("RT @"):
            continue
        tweets.append(tweet)
    return tweets


def longest_chain(root_id: str, children: dict[str, list[str]]) -> list[str]:
    best = [root_id]

    def walk(current: str, path: list[str]) -> None:
        nonlocal best
        kids = children.get(current, [])
        if not kids:
            if len(path) > len(best):
                best = path[:]
            return
        for child in kids:
            walk(child, path + [child])

    walk(root_id, [root_id])
    return best


def detect_threads(
    tweets: list[dict], max_gap_seconds: int, min_tweets: int
) -> list[tuple[dict, list[str]]]:
    by_id = {t["id_str"]: t for t in tweets}
    created = {t["id_str"]: parse_created(t["created_at"]) for t in tweets}
    children: dict[str, list[str]] = defaultdict(list)
    for tweet in tweets:
        parent = tweet.get("in_reply_to_status_id_str")
        if tweet.get("in_reply_to_user_id") != SELF_ID or not parent:
            continue
        if parent not in by_id:
            continue
        gap = (created[tweet["id_str"]] - created[parent]).total_seconds()
        if 0 <= gap <= max_gap_seconds:
            children[parent].append(tweet["id_str"])
    for parent in children:
        children[parent].sort(key=lambda i: created[i])

    found = []
    for tweet in tweets:
        if tweet.get("in_reply_to_user_id"):
            continue
        chain = longest_chain(tweet["id_str"], children)
        if len(chain) >= min_tweets:
            found.append((tweet, chain))
    found.sort(key=lambda item: int(item[0].get("favorite_count") or 0), reverse=True)
    return found


def copy_media(tweet_ids: set[str], src: Path, dest: Path) -> int:
    dest.mkdir(parents=True, exist_ok=True)
    copied = 0
    for tweet_id in tweet_ids:
        for path in src.glob(f"{tweet_id}-*"):
            shutil.copy2(path, dest / path.name)
            copied += 1
    return copied


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, default=Path("data"))
    parser.add_argument("--out", type=Path, default=Path("docs"))
    parser.add_argument("--threads", type=int, default=50)
    parser.add_argument("--tweets", type=int, default=300)
    parser.add_argument("--max-gap-minutes", type=int, default=60)
    parser.add_argument("--min-tweets", type=int, default=3)
    args = parser.parse_args()

    tweets = load_tweets(args.archive)
    by_id = {t["id_str"]: t for t in tweets}
    media_src = args.archive / "tweets_media"
    all_threads = detect_threads(tweets, args.max_gap_minutes * 60, args.min_tweets)
    selected_threads = all_threads[: args.threads]
    thread_tweet_ids = {tid for _, chain in all_threads for tid in chain}

    standalone = []
    for tweet in tweets:
        if tweet.get("in_reply_to_user_id"):
            continue
        if tweet["id_str"] in thread_tweet_ids:
            continue
        standalone.append(tweet)
    standalone.sort(key=lambda t: int(t.get("favorite_count") or 0), reverse=True)
    selected_tweets = standalone[: args.tweets]

    out_data = args.out / "data"
    out_media = args.out / "media"
    if out_data.exists():
        shutil.rmtree(out_data)
    if out_media.exists():
        shutil.rmtree(out_media)

    needed_ids = {t["id_str"] for t in selected_tweets}
    for _, chain in selected_threads:
        needed_ids.update(chain)
    copied = copy_media(needed_ids, media_src, out_media)

    thread_index = []
    for root, chain in selected_threads:
        created = parse_created(root["created_at"])
        body = [serialize_tweet(by_id[tid], media_src) for tid in chain]
        # serialize via by_id
        write_json(out_data / "threads" / f"{root['id_str']}.json", {"id": root["id_str"], "tweets": body})
        thread_index.append(
            {
                "id": root["id_str"],
                "date": created.strftime("%Y-%m-%d"),
                "year": created.year,
                "likes": int(root.get("favorite_count") or 0),
                "rts": int(root.get("retweet_count") or 0),
                "excerpt": excerpt(expand_text(root)),
                "n": len(chain),
            }
        )
    write_json(out_data / "threads-index.json", {"handle": HANDLE, "threads": thread_index})

    by_month: dict[str, list[dict]] = defaultdict(list)
    for tweet in selected_tweets:
        created = parse_created(tweet["created_at"])
        key = created.strftime("%Y-%m")
        by_month[key].append(serialize_tweet(tweet, media_src))
    for key, items in by_month.items():
        items.sort(key=lambda t: t["datetime"], reverse=True)
        write_json(out_data / f"tweets-{key}.json", {"month": key, "tweets": items})

    years = sorted({int(k.split("-")[0]) for k in by_month})
    calendar: dict[str, list[dict]] = {}
    default_key = None
    default_score = (-1, -1)
    for year in years:
        months = []
        for month in range(1, 13):
            key = f"{year}-{month:02d}"
            items = by_month.get(key, [])
            count = len(items)
            likes_max = max((t["likes"] for t in items), default=0)
            months.append({"count": count, "likes_max": likes_max})
            if count and (count, likes_max) > default_score:
                default_score = (count, likes_max)
                default_key = key
        calendar[str(year)] = months
    if default_key is None and years:
        default_key = f"{years[-1]}-01"

    write_json(
        out_data / "tweets-index.json",
        {
            "handle": HANDLE,
            "years": years,
            "default": default_key,
            "calendar": calendar,
        },
    )

    print(f"tweets parsed (no RTs): {len(tweets)}")
    print(f"burst threads: {len(all_threads)}")
    print(f"wrote threads: {len(selected_threads)}")
    print(f"wrote standalone tweets: {len(selected_tweets)}")
    print(f"month files: {len(by_month)}")
    print(f"media copied: {copied}")
    print(f"default month: {default_key}")


if __name__ == "__main__":
    main()
