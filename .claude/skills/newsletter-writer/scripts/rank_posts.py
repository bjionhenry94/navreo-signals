#!/usr/bin/env python3
"""
rank_posts.py — Rank a LinkedIn / AuthoredUp post export by performance.

The newsletter-writer skill draws each newsletter from ONE high-performing post.
This script does the boring, deterministic part: parse the CSV (which has
multi-line quoted post bodies), compute a performance score per post, and print a
ranked table plus the full text of the top N so the model can pick topics and
classify each as personal-story vs tactical/opinion by reading them.

It does NOT decide what is a "personal story" — that is a judgement call the
model makes by reading the text. This script only ranks and surfaces.

Usage:
    python3 rank_posts.py /path/to/posts_export.csv [--top 25]

Columns it expects (LinkedIn/AuthoredUp export, ';' delimited):
    text, impression_count, reaction_count, comment_count, repost_count,
    view_count, content_type, post_published_at
Missing columns are tolerated (treated as 0 / blank).
"""
import csv
import sys
import argparse

csv.field_size_limit(10**7)


def num(x):
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", help="Path to the post export CSV")
    ap.add_argument("--top", type=int, default=25, help="How many top posts to print full text for")
    ap.add_argument("--delimiter", default=";", help="CSV delimiter (LinkedIn export uses ';')")
    args = ap.parse_args()

    with open(args.path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter=args.delimiter))

    for r in rows:
        # impression_count is the real reach figure; view_count often exports as 0.
        impr = num(r.get("impression_count")) or num(r.get("view_count"))
        re_ = num(r.get("reaction_count"))
        c = num(r.get("comment_count"))
        rp = num(r.get("repost_count"))
        r["_impr"] = impr
        # Engagement score: comments and reposts signal stronger intent than likes,
        # so they are weighted up. This is the headline ranking number.
        r["_eng"] = re_ + (c * 3) + (rp * 5)
        r["_re"], r["_c"], r["_rp"] = re_, c, rp

    print(f"TOTAL POSTS: {len(rows)}\n")

    # Two rankings, because reach and engagement disagree (a post can be widely
    # seen but spark little conversation, or vice versa). Topics that score well
    # on BOTH are the safest newsletter source material.
    by_impr = sorted(rows, key=lambda r: -r["_impr"])
    by_eng = sorted(rows, key=lambda r: -r["_eng"])

    def line(r):
        txt = " ".join(r.get("text", "").split())[:75]
        ct = (r.get("content_type") or "")[:6]
        return f'{r["_impr"]:>6} impr | {r["_eng"]:>4} eng ({r["_re"]}r/{r["_c"]}c/{r["_rp"]}rp) | {ct:<6} | {txt}'

    print("=== TOP BY REACH (impressions) ===")
    for r in by_impr[: args.top]:
        print(line(r))

    print("\n=== TOP BY ENGAGEMENT (weighted) ===")
    for r in by_eng[: args.top]:
        print(line(r))

    print("\n\n=== FULL TEXT OF TOP", args.top, "BY REACH ===")
    print("(read these to pick topics and to classify each as personal-story vs tactical/opinion)\n")
    for i, r in enumerate(by_impr[: args.top], 1):
        print(f"\n----- #{i}  |  {r['_impr']} impr  |  {r['_eng']} eng  |  {r.get('post_published_at','')[:10]} -----")
        print(r.get("text", "").strip())


if __name__ == "__main__":
    main()
