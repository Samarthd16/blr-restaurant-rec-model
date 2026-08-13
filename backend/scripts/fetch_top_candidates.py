"""
Phase B of the dataset-scaling pass: fetch full Place Details (incl. reviews
-- the expensive Enterprise+Atmosphere SKU, ~$40/1000 calls) for only the
TOP_N highest-rated-count candidates from places_search.json that don't
already have full details fetched (see indiranagar_places.json,
cafes_sample_50.json).

Requires search_dataset.py to have been rerun first with rating fields in
its field mask (Pro SKU, far cheaper) so candidates can be ranked before
paying for reviews on them.

Idempotent (upsert by place_id) and incrementally saved after every place,
same resilience pattern as fetch_area_details.py.

Input:  backend/data/places_search.json
Output: backend/data/expanded_places.json
"""

import json
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ["GCP_PLACES_API"]
DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"
DATA_DIR = Path(__file__).parent.parent / "data"
SEARCH_DATA_PATH = DATA_DIR / "places_search.json"
ALREADY_FETCHED_PATHS = [DATA_DIR / "indiranagar_places.json", DATA_DIR / "cafes_sample_50.json"]
OUT_PATH = DATA_DIR / "expanded_places.json"

TOP_N = 200

FIELD_MASK = ",".join(
    [
        "id",
        "displayName",
        "formattedAddress",
        "location",
        "rating",
        "userRatingCount",
        "priceLevel",
        "types",
        "regularOpeningHours",
        "reviews",
    ]
)


def get_place_details(place_id: str, max_retries: int = 3) -> dict:
    for attempt in range(max_retries):
        try:
            resp = requests.get(
                DETAILS_URL.format(place_id=place_id),
                headers={
                    "X-Goog-Api-Key": API_KEY,
                    "X-Goog-FieldMask": FIELD_MASK,
                },
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()
        except (requests.ConnectionError, requests.Timeout) as e:
            if attempt == max_retries - 1:
                raise
            wait = 2 ** attempt
            print(f"    network error ({e.__class__.__name__}), retrying in {wait}s...")
            time.sleep(wait)


def load_already_fetched_ids() -> set[str]:
    ids = set()
    for path in ALREADY_FETCHED_PATHS:
        if not path.exists():
            continue
        raw = json.loads(path.read_text(encoding="utf-8"))
        entries = raw.values() if isinstance(raw, dict) else raw
        for entry in entries:
            ids.add(entry["id"])
    return ids


def canonical_area(matched: list[dict]) -> str:
    # a place can be matched under multiple areas (overlapping neighborhood
    # boundaries in the search sweep) -- pick whichever area matched most
    # often, tie-broken by first occurrence, same mechanical-not-clever
    # spirit as the rest of this pipeline.
    counts: dict[str, int] = {}
    order: list[str] = []
    for m in matched:
        area = m["area"]
        if area not in counts:
            order.append(area)
        counts[area] = counts.get(area, 0) + 1
    return max(order, key=lambda a: counts[a])


def load_existing() -> dict:
    if OUT_PATH.exists():
        return json.loads(OUT_PATH.read_text(encoding="utf-8"))
    return {}


def save(dataset: dict):
    OUT_PATH.write_text(json.dumps(dataset, indent=2, ensure_ascii=False), encoding="utf-8")


def main():
    search_data = json.loads(SEARCH_DATA_PATH.read_text(encoding="utf-8"))
    already_fetched = load_already_fetched_ids()

    candidates = [
        p for p in search_data.values()
        if p["id"] not in already_fetched and p.get("userRatingCount") is not None
    ]
    candidates.sort(key=lambda p: p["userRatingCount"], reverse=True)
    top_candidates = candidates[:TOP_N]

    print(f"{len(search_data)} total candidates, {len(already_fetched)} already have full details.")
    print(f"{len(candidates)} eligible (have rating data, not yet fetched).")
    print(f"Fetching top {len(top_candidates)} by rating count.")

    dataset = load_existing()
    print(f"{len(dataset)} already fetched in this batch, resuming.")

    for i, candidate in enumerate(top_candidates, 1):
        place_id = candidate["id"]
        if place_id in dataset:
            continue

        area = canonical_area(candidate["matched"])
        categories = sorted({m["category"] for m in candidate["matched"] if m["area"] == area})
        name = candidate["displayName"]["text"]
        print(f"[{i}/{len(top_candidates)}] Fetching {name} ({area}, {candidate['userRatingCount']} ratings)...")

        details = get_place_details(place_id)
        details["_categories"] = categories
        details["_area"] = area
        dataset[place_id] = details

        save(dataset)  # incremental -- survives a crash mid-run

    print(f"\nDone. {len(dataset)} places -> {OUT_PATH}")


if __name__ == "__main__":
    main()
