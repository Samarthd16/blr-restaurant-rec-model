"""
One-off diagnostic: distribution of Google's user_rating_count (total ratings
a place has ever received -- a popularity/credibility signal) across the
current dataset. Not the same as review_texts count, which is always capped
at ~5 per place by the Places API regardless of a place's real popularity.

Input:  backend/data/normalized_places.json
Output: backend/sample_queries_to_test/review_count_distribution.png
"""

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

IN_PATH = Path(__file__).parent.parent / "data" / "normalized_places.json"
OUT_PATH = Path(__file__).parent.parent / "sample_queries_to_test" / "review_count_distribution.png"

THRESHOLD = 250


def main():
    places = json.loads(IN_PATH.read_text(encoding="utf-8"))
    counts = np.array([p["user_rating_count"] for p in places if p["user_rating_count"] is not None])

    print(f"n = {len(counts)}")
    print(f"min={counts.min()}, max={counts.max()}")
    for pct in (10, 25, 50, 75, 90, 95):
        print(f"  p{pct}: {np.percentile(counts, pct):.0f}")
    below = (counts < THRESHOLD).sum()
    print(f"\nBelow {THRESHOLD} ratings: {below}/{len(counts)} ({100*below/len(counts):.0f}%)")
    print(f"At/above {THRESHOLD} ratings: {len(counts) - below}/{len(counts)} ({100*(len(counts)-below)/len(counts):.0f}%)")

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    # log-scale histogram -- linear scale would be one giant bar near 0 given
    # the 2..62242 range
    bins = np.logspace(np.log10(max(counts.min(), 1)), np.log10(counts.max()), 30)
    ax1.hist(counts, bins=bins, edgecolor="black")
    ax1.set_xscale("log")
    ax1.axvline(THRESHOLD, color="red", linestyle="--", label=f"{THRESHOLD} ratings")
    ax1.set_xlabel("user_rating_count (log scale)")
    ax1.set_ylabel("number of places")
    ax1.set_title("Distribution of total Google ratings per place")
    ax1.legend()

    # boxplot to make outliers explicit
    ax2.boxplot(counts, vert=True)
    ax2.set_yscale("log")
    ax2.axhline(THRESHOLD, color="red", linestyle="--", label=f"{THRESHOLD} ratings")
    ax2.set_ylabel("user_rating_count (log scale)")
    ax2.set_title("Outliers")
    ax2.legend()

    fig.tight_layout()
    OUT_PATH.parent.mkdir(exist_ok=True)
    fig.savefig(OUT_PATH, dpi=150)
    print(f"\nSaved chart -> {OUT_PATH}")


if __name__ == "__main__":
    main()