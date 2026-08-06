"""
Step 2 of raw-data -> knowledge-graph pipeline: turn normalized place records
into actual graph elements -- nodes and edges -- per the schema locked in the
context doc (§8.1). This is the "mechanical" half of the graph: no LLM, no
embeddings, just deciding what's a node vs. an edge vs. a node property.

- `Place` node: one per place. Its own single-place facts (rating, price,
  lat/lng) stay as *properties* on the node -- they're facts ABOUT one place,
  not relationships TO another entity, so they don't become edges.
- `Area` node: one per unique area name. Multiple places share an Area node --
  that's what makes it worth being a node instead of just a Place property.
- `LOCATED_IN` edge: Place -> Area, one per place.
- `Category` node: one per unique search category (cafe, coffee shop,
  dessert shop, bar, brewery, coffee roaster) -- a coarse, mechanical "type
  of food" signal, already sitting on every place from the search sweep.
  NOT the same as the locked `Specialty`/`FAMOUS_FOR` node (§8.1) -- that's
  the finer-grained, LLM-derived version (matcha, croissants specifically),
  still pending. This is the cheap version, ready now.
- `IN_CATEGORY` edge: Place -> Category, one per category a place matched.

(Vibe/Specialty/Diet nodes and their edges come later, from the LLM
enrichment pass -- not mechanical, so not built here.)

Input:  backend/data/normalized_places.json
Output: backend/data/graph_elements.json
"""

import json
from pathlib import Path

IN_PATH = Path(__file__).parent.parent / "data" / "normalized_places.json"
OUT_PATH = Path(__file__).parent.parent / "data" / "graph_elements.json"


def main():
    places = json.loads(IN_PATH.read_text(encoding="utf-8"))

    place_nodes = []
    area_names = set()
    category_names = set()
    located_in_edges = []
    in_category_edges = []

    for p in places:
        place_nodes.append(
            {
                "id": p["id"],
                "name": p["name"],
                "rating": p["rating"],
                "user_rating_count": p["user_rating_count"],
                "tier": p.get("tier"),
                "price_level": p["price_level"],
                "lat": p["lat"],
                "lng": p["lng"],
            }
        )

        if p["area"]:
            area_names.add(p["area"])
            located_in_edges.append({"place_id": p["id"], "area": p["area"]})

        for category in p.get("categories", []):
            category_names.add(category)
            in_category_edges.append({"place_id": p["id"], "category": category})

    area_nodes = [{"name": name} for name in sorted(area_names)]
    category_nodes = [{"name": name} for name in sorted(category_names)]

    graph_elements = {
        "nodes": {
            "Place": place_nodes,
            "Area": area_nodes,
            "Category": category_nodes,
        },
        "edges": {
            "LOCATED_IN": located_in_edges,
            "IN_CATEGORY": in_category_edges,
        },
    }

    OUT_PATH.write_text(json.dumps(graph_elements, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Place nodes: {len(place_nodes)}")
    print(f"Area nodes: {len(area_nodes)} -> {sorted(area_names)}")
    print(f"Category nodes: {len(category_nodes)} -> {sorted(category_names)}")
    print(f"LOCATED_IN edges: {len(located_in_edges)}")
    print(f"IN_CATEGORY edges: {len(in_category_edges)}")
    print(f"\nWrote {OUT_PATH}")


if __name__ == "__main__":
    main()
