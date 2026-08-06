"""
Place-to-Place proximity (loaded as the :ADJACENT_TO relationship between
Place nodes -- see load_graph.py): connects places within actual walking
distance of each other. Different from Area NEAR (coarse, neighborhood-level,
used for search-expansion fallback) -- this is fine-grained and doubles as
a free proxy for cafe-hopping/itinerary signal (no blog scraping needed,
just the coordinates we already have).

Distance-capped AND top-K, not just one or the other:
- Distance cap (WALK_THRESHOLD_KM) gives "walking distance" an absolute
  meaning -- without it, places in sparse areas could get connected to
  things that aren't actually walkable.
- Top-K per place keeps dense clusters (e.g. ~200 cafes packed into
  Indiranagar) from turning into a near-complete graph where everything is
  within range of everything -- each place only keeps its K closest
  neighbors, even if far more than K fall inside the distance cap.

Note: this is O(n^2) pairwise comparison, fine at a few hundred places,
would need a spatial index (e.g. geohash bucketing) at full-city scale.

Input:  backend/data/normalized_places.json
Output: backend/data/place_proximity.json
"""

import json
import math
from collections import defaultdict
from pathlib import Path

IN_PATH = Path(__file__).parent.parent / "data" / "normalized_places.json"
OUT_PATH = Path(__file__).parent.parent / "data" / "place_proximity.json"

WALK_THRESHOLD_KM = 0.5
K_NEAREST = 4


def haversine_km(lat1, lng1, lat2, lng2) -> float:
    r = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def main():
    places = json.loads(IN_PATH.read_text(encoding="utf-8"))
    places = [p for p in places if p["lat"] is not None and p["lng"] is not None]

    # nearest K within the walk threshold, per place
    nearest_by_place = defaultdict(list)
    for p in places:
        distances = sorted(
            (
                (haversine_km(p["lat"], p["lng"], other["lat"], other["lng"]), other["id"])
                for other in places
                if other["id"] != p["id"]
            )
        )
        within_range = [(d, oid) for d, oid in distances if d <= WALK_THRESHOLD_KM]
        nearest_by_place[p["id"]] = within_range[:K_NEAREST]

    # symmetric: materialize a pair if EITHER side picked the other as a
    # top-K neighbor, deduped
    seen = set()
    edges = []
    for place_id, neighbors in nearest_by_place.items():
        for dist, other_id in neighbors:
            key = tuple(sorted((place_id, other_id)))
            if key not in seen:
                seen.add(key)
                edges.append({"place_a": key[0], "place_b": key[1], "distance_km": round(dist, 3)})

    OUT_PATH.write_text(json.dumps(edges, indent=2, ensure_ascii=False), encoding="utf-8")

    total_pairs = len(places) * (len(places) - 1) // 2
    print(f"Checked {total_pairs} pairs, {len(edges)} edges after {WALK_THRESHOLD_KM}km cap + top-{K_NEAREST}.")
    for e in sorted(edges, key=lambda e: e["distance_km"])[:10]:
        name_a = next(p["name"] for p in places if p["id"] == e["place_a"])
        name_b = next(p["name"] for p in places if p["id"] == e["place_b"])
        print(f"  {name_a} <-> {name_b}: {e['distance_km']}km")

    print(f"\nWrote {len(edges)} Place ADJACENT_TO edges -> {OUT_PATH}")


if __name__ == "__main__":
    main()