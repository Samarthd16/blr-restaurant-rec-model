"""
Step 6 of raw-data -> knowledge-graph pipeline: load graph_elements.json
(built mechanically in step 2, no LLM/embeddings involved) into the Neo4j
Aura instance via Cypher MERGE.

MERGE, not CREATE, throughout -- re-running this script upserts instead of
duplicating nodes/edges, same idempotency principle as the rest of the
project's ingestion (context doc §11).
"""

import json
import os
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

URI = os.environ["NEO4J_URI"]
AUTH = (os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"])
DATA_PATH = Path(__file__).parent.parent / "data" / "graph_elements.json"
ADJACENCY_PATH = Path(__file__).parent.parent / "data" / "area_adjacency.json"
PROXIMITY_PATH = Path(__file__).parent.parent / "data" / "place_proximity.json"


def ensure_constraints(session):
    session.run(
        "CREATE CONSTRAINT place_id IF NOT EXISTS FOR (p:Place) REQUIRE p.id IS UNIQUE"
    )
    session.run(
        "CREATE CONSTRAINT area_name IF NOT EXISTS FOR (a:Area) REQUIRE a.name IS UNIQUE"
    )
    session.run(
        "CREATE CONSTRAINT category_name IF NOT EXISTS FOR (c:Category) REQUIRE c.name IS UNIQUE"
    )
    # Lucene-backed full-text index -- tolerates typos/word-order via fuzzy
    # (~) queries, unlike a plain CONTAINS/equality match. Used to resolve
    # a user-named reference place ("Toitt" -> "Toit") in query_intent.py.
    session.run(
        "CREATE FULLTEXT INDEX place_name_fulltext IF NOT EXISTS FOR (p:Place) ON EACH [p.name]"
    )


TIER_LABELS = ["S", "A", "B"]


def load_places(session, places: list[dict]):
    session.run(
        """
        UNWIND $places AS place
        MERGE (p:Place {id: place.id})
        REMOVE p:S, p:A, p:B
        SET p.name = place.name,
            p.rating = place.rating,
            p.user_rating_count = place.user_rating_count,
            p.tier = place.tier,
            p.price_level = place.price_level,
            p.lat = place.lat,
            p.lng = place.lng
        """,
        places=places,
    )

    # Cypher doesn't support parameterized labels, so tier (one of our own
    # fixed S/A/B values, not external input) gets interpolated directly --
    # this is what lets Neo4j Browser auto-color by tier via its label
    # legend, since it colors by label, not by arbitrary property value.
    by_tier = defaultdict(list)
    for p in places:
        if p.get("tier") in TIER_LABELS:
            by_tier[p["tier"]].append(p["id"])

    for tier, ids in by_tier.items():
        session.run(
            f"""
            UNWIND $ids AS id
            MATCH (p:Place {{id: id}})
            SET p:{tier}
            """,
            ids=ids,
        )


def load_areas(session, areas: list[dict]):
    session.run(
        """
        UNWIND $areas AS area
        MERGE (a:Area {name: area.name})
        """,
        areas=areas,
    )


def load_located_in(session, edges: list[dict]):
    session.run(
        """
        UNWIND $edges AS edge
        MATCH (p:Place {id: edge.place_id})
        MATCH (a:Area {name: edge.area})
        MERGE (p)-[:LOCATED_IN]->(a)
        """,
        edges=edges,
    )


def load_categories(session, categories: list[dict]):
    session.run(
        """
        UNWIND $categories AS category
        MERGE (c:Category {name: category.name})
        """,
        categories=categories,
    )


def load_in_category(session, edges: list[dict]):
    session.run(
        """
        UNWIND $edges AS edge
        MATCH (p:Place {id: edge.place_id})
        MATCH (c:Category {name: edge.category})
        MERGE (p)-[:IN_CATEGORY]->(c)
        """,
        edges=edges,
    )


def load_area_near(session, edges: list[dict]):
    # Fully recomputed from source data every run (not incrementally
    # accumulated) -- clear old edges first so a shrinking result set
    # (e.g. a tighter threshold) actually removes what no longer qualifies,
    # since MERGE below only adds/updates, never deletes.
    session.run("MATCH (:Area)-[r:NEAR]-(:Area) DELETE r")
    session.run(
        """
        UNWIND $edges AS edge
        MATCH (a:Area {name: edge.from_area})
        MATCH (b:Area {name: edge.to_area})
        MERGE (a)-[r:NEAR]->(b)
        SET r.distance_km = edge.distance_km
        """,
        edges=edges,
    )


def load_place_adjacent_to(session, edges: list[dict]):
    # Place-to-Place, real walking-distance proximity -- named ADJACENT_TO.
    # Symmetric -- one edge per pair, not duplicated both directions,
    # traverse with an undirected MATCH. Cleared first, same reasoning as
    # load_area_near above.
    session.run("MATCH (:Place)-[r:ADJACENT_TO]-(:Place) DELETE r")
    session.run(
        """
        UNWIND $edges AS edge
        MATCH (a:Place {id: edge.place_a})
        MATCH (b:Place {id: edge.place_b})
        MERGE (a)-[r:ADJACENT_TO]-(b)
        SET r.distance_km = edge.distance_km
        """,
        edges=edges,
    )


def print_summary(session):
    result = session.run(
        """
        MATCH (n)
        RETURN labels(n)[0] AS label, count(*) AS count
        ORDER BY label
        """
    )
    print("\n--- Nodes in DB ---")
    for record in result:
        print(f"  {record['label']}: {record['count']}")

    result = session.run(
        """
        MATCH ()-[r]->()
        RETURN type(r) AS rel_type, count(*) AS count
        ORDER BY rel_type
        """
    )
    print("--- Relationships in DB ---")
    for record in result:
        print(f"  {record['rel_type']}: {record['count']}")


def main():
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))

    with GraphDatabase.driver(URI, auth=AUTH) as driver:
        with driver.session() as session:
            print("Ensuring constraints...")
            ensure_constraints(session)

            print(f"Loading {len(data['nodes']['Place'])} Place nodes...")
            load_places(session, data["nodes"]["Place"])

            print(f"Loading {len(data['nodes']['Area'])} Area nodes...")
            load_areas(session, data["nodes"]["Area"])

            print(f"Loading {len(data['edges']['LOCATED_IN'])} LOCATED_IN edges...")
            load_located_in(session, data["edges"]["LOCATED_IN"])

            print(f"Loading {len(data['nodes']['Category'])} Category nodes...")
            load_categories(session, data["nodes"]["Category"])

            print(f"Loading {len(data['edges']['IN_CATEGORY'])} IN_CATEGORY edges...")
            load_in_category(session, data["edges"]["IN_CATEGORY"])

            if ADJACENCY_PATH.exists():
                adjacency_edges = json.loads(ADJACENCY_PATH.read_text(encoding="utf-8"))
                print(f"Loading {len(adjacency_edges)} Area NEAR edges...")
                load_area_near(session, adjacency_edges)
            else:
                print(f"Skipping Area NEAR -- {ADJACENCY_PATH} not found (run build_adjacency.py first).")

            if PROXIMITY_PATH.exists():
                proximity_edges = json.loads(PROXIMITY_PATH.read_text(encoding="utf-8"))
                print(f"Loading {len(proximity_edges)} Place ADJACENT_TO edges...")
                load_place_adjacent_to(session, proximity_edges)
            else:
                print(f"Skipping Place ADJACENT_TO -- {PROXIMITY_PATH} not found (run build_proximity.py first).")

            print_summary(session)


if __name__ == "__main__":
    main()
