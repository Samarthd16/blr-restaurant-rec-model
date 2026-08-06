"""
Removes any :Place node from Neo4j whose id is no longer present in
graph_elements.json. Needed because load_graph.py only MERGEs (adds/updates)
-- it never deletes, so a place dropped from the source data (e.g. a bad
out-of-region match caught by normalize_places.py's bounding-box check)
would otherwise stay in the graph forever.

Run this BEFORE re-running load_graph.py on a regenerated graph_elements.json.
"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

URI = os.environ["NEO4J_URI"]
AUTH = (os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"])
DATA_PATH = Path(__file__).parent.parent / "data" / "graph_elements.json"


def main():
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    current_ids = [p["id"] for p in data["nodes"]["Place"]]

    with GraphDatabase.driver(URI, auth=AUTH) as driver:
        with driver.session() as session:
            result = session.run(
                """
                MATCH (p:Place)
                WHERE NOT p.id IN $current_ids
                RETURN p.id AS id, p.name AS name
                """,
                current_ids=current_ids,
            )
            stale = [(r["id"], r["name"]) for r in result]

            if not stale:
                print("No stale Place nodes found.")
                return

            print(f"Removing {len(stale)} stale Place node(s):")
            for place_id, name in stale:
                print(f"  {name} ({place_id})")

            session.run(
                """
                MATCH (p:Place)
                WHERE NOT p.id IN $current_ids
                DETACH DELETE p
                """,
                current_ids=current_ids,
            )
            print("Done.")


if __name__ == "__main__":
    main()