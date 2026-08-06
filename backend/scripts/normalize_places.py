"""
Step 1 of raw-data -> knowledge-graph pipeline: flatten raw Places API
Details responses (nested, API-shaped, from multiple source files/shapes)
into one clean record per place with just the fields the graph schema
(context doc §8.1) actually needs.

Inputs:
  backend/data/cafes_sample_50.json    (list, one raw place per entry,
                                         fields _sample_area/_sample_region)
  backend/data/indiranagar_places.json (dict keyed by place_id, fields
                                         _area/_categories)
Output: backend/data/normalized_places.json (one flat dict per place, deduped
        by id -- a place can appear in both sources)
"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DATA_DIR = Path(__file__).parent.parent / "data"
SOURCES = [
    ("cafes_sample_50.json", "list"),
    ("indiranagar_places.json", "dict"),
]
OUT_PATH = DATA_DIR / "normalized_places.json"

# Generous Bengaluru metro bounding box -- catches Text Search mismatches
# from other cities/regions (e.g. a same-named cafe in Mysuru), not meant
# to be precise.
BLR_LAT_RANGE = (12.7, 13.2)
BLR_LNG_RANGE = (77.35, 77.85)

# Minimum Google user_rating_count (total ratings, not review text count --
# see plot_review_count_buckets.py) for a place to make the graph. Chosen
# from the bucket chart to cut low-confidence/obscure places while keeping
# a reasonable share of the dataset. Set in .env so it's easy to tune without
# editing this file.
MIN_RATING_COUNT = int(os.environ["MIN_RATING_COUNT"])

# Popularity tier by user_rating_count, applied after the MIN_RATING_COUNT
# filter above -- so in practice every place lands in B/A/S, nothing lower.
TIER_THRESHOLDS = [
    (2500, "S"),
    (1000, "A"),
    (500, "B"),
]


def rating_tier(user_rating_count) -> str | None:
    count = user_rating_count or 0
    for threshold, tier in TIER_THRESHOLDS:
        if count >= threshold:
            return tier
    return None


def in_bengaluru(lat, lng) -> bool:
    if lat is None or lng is None:
        return False
    return BLR_LAT_RANGE[0] <= lat <= BLR_LAT_RANGE[1] and BLR_LNG_RANGE[0] <= lng <= BLR_LNG_RANGE[1]


def normalize(raw: dict) -> dict:
    location = raw.get("location", {})
    reviews = raw.get("reviews", [])

    area = raw.get("_area") or raw.get("_sample_area")
    # cafes_sample_50.json predates category tracking -- everything in it
    # was found via a plain "cafes" search, so backfill that one category.
    categories = raw.get("_categories") or (["cafes"] if raw.get("_sample_area") else [])

    return {
        "id": raw["id"],
        "name": raw.get("displayName", {}).get("text"),
        "area": area,
        "region": raw.get("_sample_region"),
        "categories": categories,
        "lat": location.get("latitude"),
        "lng": location.get("longitude"),
        "rating": raw.get("rating"),
        "user_rating_count": raw.get("userRatingCount"),
        "tier": rating_tier(raw.get("userRatingCount")),
        "price_level": raw.get("priceLevel"),
        "review_texts": [
            r.get("text", {}).get("text", "") for r in reviews if r.get("text")
        ],
    }


def load_source(filename: str, shape: str) -> list[dict]:
    path = DATA_DIR / filename
    if not path.exists():
        print(f"Skipping {filename} -- not found.")
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return list(raw.values()) if shape == "dict" else raw


def main():
    # dedup by id -- later sources win (indiranagar_places.json has richer
    # category data than cafes_sample_50.json for any overlapping place)
    by_id: dict[str, dict] = {}
    for filename, shape in SOURCES:
        for raw in load_source(filename, shape):
            by_id[raw["id"]] = normalize(raw)

    normalized = list(by_id.values())

    in_blr = [p for p in normalized if in_bengaluru(p["lat"], p["lng"])]
    dropped_location = [p for p in normalized if p not in in_blr]
    if dropped_location:
        print(f"Dropping {len(dropped_location)} place(s) outside the Bengaluru bounding box:")
        for p in dropped_location:
            print(f"  {p['name']} ({p['area']}): lat={p['lat']}, lng={p['lng']}")

    valid = [p for p in in_blr if (p["user_rating_count"] or 0) >= MIN_RATING_COUNT]
    dropped_rating_count = [p for p in in_blr if p not in valid]
    if dropped_rating_count:
        print(f"\nDropping {len(dropped_rating_count)} place(s) below {MIN_RATING_COUNT} ratings:")
        for p in dropped_rating_count:
            print(f"  {p['name']} ({p['area']}): {p['user_rating_count']} ratings")

    OUT_PATH.write_text(json.dumps(valid, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nNormalized {len(valid)} places -> {OUT_PATH}")
    print("\nExample record:")
    print(json.dumps(valid[0], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
