#!/usr/bin/env python3
"""Build a static subset site from a local Twitter archive."""

from __future__ import annotations

import argparse
import json
import re
import shutil
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

SELF_ID = "533409964"
HANDLE = "johncutlefish"
TWEET_RE = re.compile(r"https://t\.co/\w+")
YTD_PREFIX = re.compile(r"^window\.YTD\.[A-Za-z0-9_]+\.part\d+\s*=\s*")
PBS_CODE = re.compile(r"/(?:media|img)/([A-Za-z0-9_-]+)\.")
WORD_RE = re.compile(r"[A-Za-z0-9']+")


def load_part(path: Path, part: str) -> list:
    raw = path.read_text(encoding="utf-8")
    prefix = f"window.YTD.tweets.{part} = "
    if raw.startswith(prefix):
        raw = raw[len(prefix) :]
    raw = raw.rstrip()
    if raw.endswith(";"):
        raw = raw[:-1]
    return json.loads(raw)


def load_ytd(path: Path) -> list:
    raw = path.read_text(encoding="utf-8")
    raw = YTD_PREFIX.sub("", raw, count=1)
    raw = raw.rstrip()
    if raw.endswith(";"):
        raw = raw[:-1]
    return json.loads(raw)


def parse_created(value: str) -> datetime:
    return datetime.strptime(value, "%a %b %d %H:%M:%S %z %Y")


def tweet_media_items(tweet: dict) -> list[dict]:
    return (tweet.get("extended_entities") or {}).get("media") or (tweet.get("entities") or {}).get("media") or []


def pbs_code(item: dict) -> str | None:
    url = item.get("media_url_https") or item.get("media_url") or ""
    match = PBS_CODE.search(url)
    return match.group(1) if match else None


def expand_text(tweet: dict, keep_media_urls: bool = False) -> str:
    text = tweet.get("full_text") or ""
    replacements: list[tuple[str, str]] = []
    entities = tweet.get("entities") or {}
    for url in entities.get("urls") or []:
        short = url.get("url")
        expanded = url.get("expanded_url") or url.get("display_url") or short
        if short and expanded:
            replacements.append((short, expanded))
    for item in tweet_media_items(tweet):
        short = item.get("url")
        if not short:
            continue
        if keep_media_urls:
            expanded = item.get("expanded_url") or item.get("media_url_https") or item.get("display_url") or ""
            replacements.append((short, expanded))
        else:
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


def index_media(media_dir: Path) -> tuple[dict[str, list[Path]], dict[str, list[Path]]]:
    by_tid: dict[str, list[Path]] = defaultdict(list)
    by_pbs: dict[str, list[Path]] = defaultdict(list)
    if not media_dir.exists():
        return by_tid, by_pbs
    for path in media_dir.iterdir():
        if path.name.startswith("."):
            continue
        tid, sep, rest = path.name.partition("-")
        if sep:
            by_tid[tid].append(path)
            by_pbs[Path(rest).stem].append(path)
    return by_tid, by_pbs


def resolve_media(tweet: dict, by_tid: dict[str, list[Path]], by_pbs: dict[str, list[Path]]) -> list[Path]:
    found = list(by_tid.get(tweet["id_str"], []))
    if found:
        return sorted(found, key=lambda p: p.name)
    extras: list[Path] = []
    seen: set[str] = set()
    for item in tweet_media_items(tweet):
        code = pbs_code(item)
        for path in by_pbs.get(code or "", []):
            if path.name not in seen:
                seen.add(path.name)
                extras.append(path)
    return extras


def dest_media_name(tweet_id: str, src: Path) -> str:
    if src.name.startswith(f"{tweet_id}-"):
        return src.name
    _, _, rest = src.name.partition("-")
    return f"{tweet_id}-{rest}" if rest else f"{tweet_id}-{src.name}"


def serialize_tweet(tweet: dict, media_names: list[str]) -> dict:
    created = parse_created(tweet["created_at"])
    return {
        "id": tweet["id_str"],
        "date": created.strftime("%Y-%m-%d"),
        "datetime": created.isoformat(),
        "likes": int(tweet.get("favorite_count") or 0),
        "rts": int(tweet.get("retweet_count") or 0),
        "text": expand_text(tweet, keep_media_urls=not media_names),
        "media": [f"media/{name}" for name in media_names],
    }


def load_all_posts(archive: Path) -> list[dict]:
    wraps = load_part(archive / "tweets.js", "part0")
    wraps += load_part(archive / "tweets-part1.js", "part1")
    return [wrap["tweet"] for wrap in wraps]


def load_tweets(archive: Path) -> list[dict]:
    tweets = []
    for tweet in load_all_posts(archive):
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


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def archive_stats(archive: Path, tweets: list[dict], all_threads: list[tuple[dict, list[str]]]) -> dict:
    created = [parse_created(t["created_at"]) for t in tweets]
    thread_ids = {tid for _, chain in all_threads for tid in chain}
    replies = [t for t in tweets if t.get("in_reply_to_user_id")]
    replies_others = [t for t in replies if t.get("in_reply_to_user_id") != SELF_ID]
    pictures = sum(1 for t in tweets if tweet_media_items(t))
    words = sum(len(WORD_RE.findall(expand_text(t))) for t in tweets)
    year_counts = Counter(d.year for d in created)
    peak_year, peak_count = year_counts.most_common(1)[0]

    all_posts = load_all_posts(archive)
    retweets = sum(1 for t in all_posts if (t.get("full_text") or "").startswith("RT @"))

    dm = load_ytd(archive / "direct-message-headers.js")
    dm_msgs = 0
    dm_people: set[str] = set()
    for conv in dm:
        cid = conv["dmConversation"]["conversationId"]
        for part in cid.split("-"):
            if part and part != SELF_ID:
                dm_people.add(part)
        dm_msgs += len(conv["dmConversation"].get("messages") or [])

    followers = len(load_ytd(archive / "follower.js"))
    following = len(load_ytd(archive / "following.js"))

    return {
        "first": min(created).strftime("%Y-%m-%d"),
        "last": max(created).strftime("%Y-%m-%d"),
        "tweets": len(tweets),
        "retweets": retweets,
        "non_thread_replies": sum(1 for t in replies if t["id_str"] not in thread_ids),
        "replies_to_others": len(replies_others),
        "people_replied_to": len({t.get("in_reply_to_user_id") for t in replies_others}),
        "dms": dm_msgs,
        "dm_people": len(dm_people),
        "likes": sum(int(t.get("favorite_count") or 0) for t in tweets),
        "retweets_received": sum(int(t.get("retweet_count") or 0) for t in tweets),
        "pictures": pictures,
        "words": words,
        "followers": followers,
        "following": following,
        "burst_threads": len(all_threads),
        "peak_year": peak_year,
        "peak_year_tweets": peak_count,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, default=Path("data"))
    parser.add_argument("--out", type=Path, default=Path("docs"))
    parser.add_argument("--threads", type=int, default=50)
    parser.add_argument("--tweets", type=int, default=500)
    parser.add_argument("--max-gap-minutes", type=int, default=60)
    parser.add_argument("--min-tweets", type=int, default=3)
    args = parser.parse_args()

    tweets = load_tweets(args.archive)
    by_id = {t["id_str"]: t for t in tweets}
    media_src = args.archive / "tweets_media"
    by_tid, by_pbs = index_media(media_src)
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
    out_media.mkdir(parents=True, exist_ok=True)

    needed_ids = {t["id_str"] for t in selected_tweets}
    for _, chain in selected_threads:
        needed_ids.update(chain)

    media_for: dict[str, list[str]] = {}
    copied = 0
    rematched = 0
    kept_links = 0
    for tid in needed_ids:
        tweet = by_id[tid]
        sources = resolve_media(tweet, by_tid, by_pbs)
        names = []
        for src in sources:
            name = dest_media_name(tid, src)
            shutil.copy2(src, out_media / name)
            names.append(name)
            copied += 1
            if not src.name.startswith(f"{tid}-"):
                rematched += 1
        media_for[tid] = names
        if tweet_media_items(tweet) and not names:
            kept_links += 1

    stats = archive_stats(args.archive, tweets, all_threads)
    write_json(out_data / "stats.json", stats)

    thread_index = []
    for root, chain in selected_threads:
        created = parse_created(root["created_at"])
        body = [serialize_tweet(by_id[tid], media_for[tid]) for tid in chain]
        write_json(out_data / "threads" / f"{root['id_str']}.json", {"id": root["id_str"], "tweets": body})
        thread_index.append(
            {
                "id": root["id_str"],
                "date": created.strftime("%Y-%m-%d"),
                "year": created.year,
                "likes": int(root.get("favorite_count") or 0),
                "rts": int(root.get("retweet_count") or 0),
                "excerpt": excerpt(expand_text(root, keep_media_urls=not media_for[root["id_str"]])),
                "n": len(chain),
            }
        )
    write_json(out_data / "threads-index.json", {"handle": HANDLE, "threads": thread_index})

    by_month: dict[str, list[dict]] = defaultdict(list)
    for tweet in selected_tweets:
        created = parse_created(tweet["created_at"])
        key = created.strftime("%Y-%m")
        by_month[key].append(serialize_tweet(tweet, media_for[tweet["id_str"]]))
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
    print(f"media copied: {copied} (rematched by image id: {rematched})")
    print(f"media missing from dump, kept photo link: {kept_links}")
    print(f"default month: {default_key}")


if __name__ == "__main__":
    main()
