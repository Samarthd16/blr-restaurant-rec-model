"""
Fetches full Place Details (incl. reviews) for every place already found
under a given area in places_search.json (from the earlier 33-area x
6-category search sweep -- no new search calls needed, we already have the
candidate list).

Carries forward each place's matched categories (cafes, dessert shops, bars,
etc.) into the output -- a free, mechanical, coarse proxy for "type of food"
ahead of the real LLM-derived FAMOUS_FOR/Specialty pass.

Idempotent (upsert by place_id) and incrementally saved after every place,
same resilience pattern as search_dataset.py after the earlier crash.
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
SEARCH_DATA_PATH = Path(__file__).parent.parent / "data" / "places_search.json"

AREA = "Indiranagar"
OUT_PATH = Path(__file__).parent.parent / "data" / f"{AREA.lower()}_places.json"

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


def load_existing() -> dict:
    if OUT_PATH.exists():
        return json.loads(OUT_PATH.read_text(encoding="utf-8"))
    return {}


def save(dataset: dict):
    OUT_PATH.write_text(json.dumps(dataset, indent=2, ensure_ascii=False), encoding="utf-8")


def main():
    search_data = json.loads(SEARCH_DATA_PATH.read_text(encoding="utf-8"))
    candidates = {
        pid: p for pid, p in search_data.items()
        if any(m["area"] == AREA for m in p["matched"])
    }
    print(f"{len(candidates)} candidate places for {AREA}.")

    dataset = load_existing()
    print(f"{len(dataset)} already fetched, {len(candidates) - len(dataset)} remaining.")

    for i, (place_id, candidate) in enumerate(candidates.items(), 1):
        if place_id in dataset:
            continue

        categories = sorted({m["category"] for m in candidate["matched"] if m["area"] == AREA})
        print(f"[{i}/{len(candidates)}] Fetching {candidate['displayName']['text']} ({', '.join(categories)})...")

        details = get_place_details(place_id)
        details["_categories"] = categories
        details["_area"] = AREA
        dataset[place_id] = details

        save(dataset)  # incremental -- survives a crash mid-run

    print(f"\nDone. {len(dataset)} places -> {OUT_PATH}")


if __name__ == "__main__":
    main()