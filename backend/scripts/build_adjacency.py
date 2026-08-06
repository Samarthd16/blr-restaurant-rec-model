"""
Step 4 of raw-data -> knowledge-graph pipeline: compute Area adjacency
(loaded as the :NEAR relationship between Area nodes -- see load_graph.py).

Mechanical, like Place/Area/LOCATED_IN -- no LLM needed. For each Area,
compute its centroid (average lat/lng of the places in it), then connect
each Area to its K nearest other Areas by centroid distance (top-k rather
than a fixed distance threshold, so it self-calibrates regardless of how
spread out the actual areas in the dataset are).

Input:  backend/data/normalized_places.json
Output: backend/data/area_adjacency.json
"""

import json
import math
from collections import defaultdict
from pathlib import Path

IN_PATH = Path(__file__).parent.parent / "data" / "normalized_places.json"
OUT_PATH = Path(__file__).parent.parent / "data" / "area_adjacency.json"

K_NEAREST = 2


def haversine_km(lat1, lng1, lat2, lng2) -> float:
    r = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def main():
    places = json.loads(IN_PATH.read_text(encoding="utf-8"))

    coords_by_area = defaultdict(list)
    for p in places:
        if p["area"] and p["lat"] is not None and p["lng"] is not None:
            coords_by_area[p["area"]].append((p["lat"], p["lng"]))

    centroids = {
        area: (
            sum(c[0] for c in coords) / len(coords),
            sum(c[1] for c in coords) / len(coords),
        )
        for area, coords in coords_by_area.items()
    }

    print("Area centroids:")
    for area, (lat, lng) in centroids.items():
        print(f"  {area}: ({lat:.4f}, {lng:.4f})")

    areas = list(centroids.keys())
    edges = set()

    print("\nNearest areas:")
    for area in areas:
        lat1, lng1 = centroids[area]
        distances = sorted(
            (
                (haversine_km(lat1, lng1, *centroids[other]), other)
                for other in areas
                if other != area
            )
        )
        nearest = distances[:K_NEAREST]
        print(f"  {area} -> {[(f'{d:.1f}km', a) for d, a in nearest]}")
        for dist, other in nearest:
            # symmetric: materialize both directions regardless of which
            # side's top-k picked it
            edges.add((area, other, round(dist, 2)))
            edges.add((other, area, round(dist, 2)))

    adjacency_edges = [
        {"from_area": a, "to_area": b, "distance_km": d} for a, b, d in sorted(edges)
    ]

    OUT_PATH.write_text(json.dumps(adjacency_edges, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n{len(adjacency_edges)} Area NEAR edges -> {OUT_PATH}")


if __name__ == "__main__":
    main()