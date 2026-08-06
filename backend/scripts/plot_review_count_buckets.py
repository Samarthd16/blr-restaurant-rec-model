"""
Plain bar chart of user_rating_count grouped into human-readable buckets --
easier to eyeball a cutoff threshold from than the log-scale histogram in
plot_review_counts.py. Also prints how many places would survive at a few
candidate thresholds, so the chart and the decision are side by side.

Input:  backend/data/normalized_places.json
Output: backend/sample_queries_to_test/review_count_buckets.png
"""

import json
from pathlib import Path

import matplotlib.pyplot as plt

IN_PATH = Path(__file__).parent.parent / "data" / "normalized_places.json"
OUT_PATH = Path(__file__).parent.parent / "sample_queries_to_test" / "review_count_buckets.png"

BUCKETS = [
    (0, 10), (10, 25), (25, 50), (50, 100), (100, 250),
    (250, 500), (500, 1000), (1000, 2500), (2500, 5000),
    (5000, 10000), (10000, float("inf")),
]
CANDIDATE_THRESHOLDS = [50, 100, 250, 500, 1000]


def bucket_label(lo, hi):
    return f"{lo}-{int(hi)}" if hi != float("inf") else f"{lo}+"


def main():
    places = json.loads(IN_PATH.read_text(encoding="utf-8"))
    counts = [p["user_rating_count"] for p in places if p["user_rating_count"] is not None]

    bucket_counts = []
    for lo, hi in BUCKETS:
        n = sum(1 for c in counts if lo <= c < hi)
        bucket_counts.append(n)

    labels = [bucket_label(lo, hi) for lo, hi in BUCKETS]

    print(f"Total places: {len(counts)}\n")
    print("Places kept at each candidate threshold (user_rating_count >= X):")
    for t in CANDIDATE_THRESHOLDS:
        kept = sum(1 for c in counts if c >= t)
        print(f"  >= {t}: {kept}/{len(counts)} kept ({100*kept/len(counts):.0f}%), {len(counts)-kept} dropped")

    fig, ax = plt.subplots(figsize=(11, 5))
    bars = ax.bar(labels, bucket_counts, edgecolor="black")
    for bar, n in zip(bars, bucket_counts):
        if n > 0:
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(), str(n),
                     ha="center", va="bottom")

    ax.set_xlabel("user_rating_count range")
    ax.set_ylabel("number of places")
    ax.set_title("How many places fall in each rating-count range")
    plt.xticks(rotation=30, ha="right")
    fig.tight_layout()

    OUT_PATH.parent.mkdir(exist_ok=True)
    fig.savefig(OUT_PATH, dpi=150)
    print(f"\nSaved chart -> {OUT_PATH}")


if __name__ == "__main__":
    main()