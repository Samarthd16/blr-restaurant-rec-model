"""
One-off exploration script: hits Places API (New) for a single neighborhood,
pulls full details (incl. reviews) for a few places, and dumps the raw JSON
to backend/data/sample_places.json so we can eyeball the actual response
shape before designing the pgvector schema / ingestion pipeline.

Not part of the real ingestion pipeline — just for poking at the data.
"""

import json
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ["GCP_PLACES_API"]
SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"

OUT_PATH = Path(__file__).parent.parent / "data" / "sample_places.json"

SEARCH_FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.rating",
        "places.userRatingCount",
        "places.priceLevel",
        "places.types",
        "places.location",
    ]
)

DETAILS_FIELD_MASK = ",".join(
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


def search_places(query: str, max_results: int = 5) -> list[dict]:
    resp = requests.post(
        SEARCH_URL,
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": API_KEY,
            "X-Goog-FieldMask": SEARCH_FIELD_MASK,
        },
        json={"textQuery": query},
    )
    resp.raise_for_status()
    return resp.json().get("places", [])[:max_results]


def get_place_details(place_id: str) -> dict:
    resp = requests.get(
        DETAILS_URL.format(place_id=place_id),
        headers={
            "X-Goog-Api-Key": API_KEY,
            "X-Goog-FieldMask": DETAILS_FIELD_MASK,
        },
    )
    resp.raise_for_status()
    return resp.json()


def main():
    query = "cafes in Indiranagar Bengaluru"
    print(f"Searching: {query!r}")
    results = search_places(query)

    print(f"Fetching full details (incl. reviews) for {len(results)} places...")
    details = [get_place_details(place["id"]) for place in results]

    OUT_PATH.parent.mkdir(exist_ok=True)
    OUT_PATH.write_text(json.dumps(details, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(details)} places to {OUT_PATH}")


if __name__ == "__main__":
    main()
