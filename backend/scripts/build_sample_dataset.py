"""
Build a small (~50 place), geographically-spread sample dataset for prototyping
the graph schema against real data. Picks a handful of neighborhoods per BLR
region (north/south/east/west/central), text-searches cafes in each, randomly
samples a few per area (not just top-ranked), then fetches full Place Details
(incl. reviews) for the deduped selection.

This is a prototyping dataset, not the real ingestion pipeline -- small and
cheap enough to rerun freely while we figure out the graph design.
"""

import json
import os
import random
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ["GCP_PLACES_API"]
SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"
OUT_PATH = Path(__file__).parent.parent / "data" / "cafes_sample_50.json"

CAFES_PER_AREA = 5

REGIONS = {
    "North": ["Hebbal", "Yelahanka"],
    "South": ["Jayanagar", "Banashankari"],
    "East": ["Indiranagar", "Whitefield"],
    "West": ["Rajajinagar", "Vijayanagar"],
    "Central": ["Koramangala", "MG Road Bengaluru"],
}

SEARCH_FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
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


def search_area(area: str) -> list[dict]:
    resp = requests.post(
        SEARCH_URL,
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": API_KEY,
            "X-Goog-FieldMask": SEARCH_FIELD_MASK,
        },
        json={"textQuery": f"cafes in {area} Bengaluru", "includedType": "cafe", "pageSize": 20},
    )
    resp.raise_for_status()
    return resp.json().get("places", [])


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
    selected: dict[str, dict] = {}  # place_id -> {region, area}

    for region, areas in REGIONS.items():
        for area in areas:
            print(f"Searching {area} ({region})...")
            results = search_area(area)
            sample = random.sample(results, min(CAFES_PER_AREA, len(results)))
            for place in sample:
                selected[place["id"]] = {"region": region, "area": area}
            print(f"  {len(results)} found, {len(sample)} sampled")

    print(f"\nFetching full details for {len(selected)} unique places...")
    dataset = []
    for place_id, meta in selected.items():
        details = get_place_details(place_id)
        details["_sample_region"] = meta["region"]
        details["_sample_area"] = meta["area"]
        dataset.append(details)

    OUT_PATH.parent.mkdir(exist_ok=True)
    OUT_PATH.write_text(json.dumps(dataset, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nWrote {len(dataset)} places to {OUT_PATH}")
    for region, areas in REGIONS.items():
        count = sum(1 for p in dataset if p["_sample_region"] == region)
        print(f"  {region}: {count}")


if __name__ == "__main__":
    main()