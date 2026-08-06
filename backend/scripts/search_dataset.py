"""
Search-only ingestion pass (phase 1 of 2): sweep BLR neighborhoods x categories
via Places API (New) Text Search, paginate each query, dedup by place_id, and
upsert into backend/data/places_search.json.

Deliberately does NOT fetch Place Details/reviews -- that's search_details.py,
run once against the deduped output of this script, so we're not paying for
reviews on places we'd find multiple times across overlapping area/category
queries.

Idempotent: re-running merges into the existing file by place_id (upsert),
matching the freshness/idempotency decision in the project doc (search-only
fields get refreshed on every re-run; a place's `matched` list only grows).
"""

import json
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

from blr_neighborhoods import BLR_NEIGHBORHOODS

load_dotenv()

API_KEY = os.environ["GCP_PLACES_API"]
SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
OUT_PATH = Path(__file__).parent.parent / "data" / "places_search.json"

# Younger-audience-skewed categories. Plain phrases, not Google's formal
# `type` enum -- we're not confident "dessert_shop"/"brewery" are valid type
# slugs, and text search already ranks well on phrases alone.
CATEGORIES = [
    "cafes",
    "coffee shops",
    "coffee roasters",
    "dessert shops",
    "bars",
    "breweries",
]

MAX_PAGES = 3  # Text Search caps around 60 results (3 pages of 20)
PAGE_TOKEN_DELAY_SECONDS = 2

FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.types",
        "nextPageToken",
    ]
)


def post_with_retries(body: dict, max_retries: int = 3) -> dict:
    for attempt in range(max_retries):
        try:
            resp = requests.post(
                SEARCH_URL,
                headers={
                    "Content-Type": "application/json",
                    "X-Goog-Api-Key": API_KEY,
                    "X-Goog-FieldMask": FIELD_MASK,
                },
                json=body,
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


def search(category: str, area: str) -> list[dict]:
    query = f"{category} in {area} Bengaluru"
    results = []
    page_token = None

    for _ in range(MAX_PAGES):
        body = {"textQuery": query}
        if page_token:
            body["pageToken"] = page_token
            time.sleep(PAGE_TOKEN_DELAY_SECONDS)

        data = post_with_retries(body)
        results.extend(data.get("places", []))
        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return results


def load_existing() -> dict:
    if OUT_PATH.exists():
        return json.loads(OUT_PATH.read_text(encoding="utf-8"))
    return {}


def save(dataset: dict):
    OUT_PATH.parent.mkdir(exist_ok=True)
    OUT_PATH.write_text(json.dumps(dataset, indent=2, ensure_ascii=False), encoding="utf-8")


def main():
    dataset = load_existing()
    print(f"Starting with {len(dataset)} places already on disk.")

    category_hits = {c: 0 for c in CATEGORIES}

    for area in BLR_NEIGHBORHOODS:
        for category in CATEGORIES:
            print(f"Searching '{category}' in {area}...")
            try:
                places = search(category, area)
            except requests.HTTPError as e:
                print(f"  FAILED: {e}")
                continue

            for place in places:
                place_id = place["id"]
                entry = dataset.setdefault(
                    place_id,
                    {
                        "id": place_id,
                        "displayName": place.get("displayName"),
                        "formattedAddress": place.get("formattedAddress"),
                        "types": place.get("types"),
                        "matched": [],
                    },
                )
                # keep freshest copy of these fields
                entry["displayName"] = place.get("displayName")
                entry["formattedAddress"] = place.get("formattedAddress")
                entry["types"] = place.get("types")
                match = {"area": area, "category": category}
                if match not in entry["matched"]:
                    entry["matched"].append(match)

            category_hits[category] += len(places)
            print(f"  {len(places)} results")

        # save after every area, not just at the end -- a crash mid-run
        # shouldn't lose everything gathered so far
        save(dataset)
        print(f"  [saved {len(dataset)} unique places so far]")

    print("\n--- Summary ---")
    for category, count in category_hits.items():
        print(f"  {category}: {count} raw hits")
    print(f"\nTotal unique places: {len(dataset)}")
    print(f"Wrote to {OUT_PATH}")


if __name__ == "__main__":
    main()
