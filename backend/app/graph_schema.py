"""
Live schema introspection: builds the schema description fed to the LLM
directly from the current Neo4j graph, instead of a hand-maintained string
that drifts out of sync as the graph changes (new categories, new areas,
new node/edge types).

Uses plain Cypher (sample one node per label, one relationship per type,
read their keys) rather than db.schema.* procedures -- avoids any
version-specific procedure availability questions, guaranteed to work
anywhere Cypher works.
"""

import os

from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

NEO4J_URI = os.environ["NEO4J_URI"]
NEO4J_AUTH = (os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"])

# Tier labels are described separately (as a note on Place), not listed as
# their own node type -- (:S), (:A), (:B) alone are meaningless without Place.
TIER_LABELS = {"S", "A", "B"}


def get_schema_context() -> str:
    # connection_timeout caps the initial connection attempt; max_transaction_retry_time
    # caps the driver's own transient-error retry loop (default 30s, with
    # exponential backoff) -- without both, a paused/unreachable Aura instance
    # can take 30+ seconds to finally raise ServiceUnavailable.
    with GraphDatabase.driver(
        NEO4J_URI, auth=NEO4J_AUTH, connection_timeout=10, max_transaction_retry_time=5
    ) as driver:
        with driver.session() as session:
            labels = session.execute_read(
                lambda tx: [r["label"] for r in tx.run("CALL db.labels() YIELD label RETURN label")]
            )
            rel_types = session.execute_read(
                lambda tx: [
                    r["relationshipType"]
                    for r in tx.run("CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType")
                ]
            )

            lines = ["Node labels and properties:"]
            for label in sorted(labels):
                if label in TIER_LABELS:
                    continue
                # label is internal DB metadata, not user input -- safe to
                # interpolate (same reasoning as the tier-label SET in
                # load_graph.py; Cypher can't parameterize labels anyway)
                sample = session.execute_read(
                    lambda tx, lbl=label: tx.run(f"MATCH (n:`{lbl}`) RETURN keys(n) AS keys LIMIT 1").single()
                )
                props = ", ".join(sorted(sample["keys"])) if sample else "(no instances yet)"
                lines.append(f"- {label} {{{props}}}")
            lines.append(
                "- Every Place ALSO carries an extra label S, A, or B (popularity tier) "
                "-- query it as (:Place:S) etc."
            )

            lines.append("\nRelationship types:")
            for rel in sorted(rel_types):
                sample = session.execute_read(
                    lambda tx, r=rel: tx.run(f"MATCH ()-[r:`{r}`]->() RETURN keys(r) AS keys LIMIT 1").single()
                )
                props = ", ".join(sorted(sample["keys"])) if sample and sample["keys"] else "(no properties)"
                lines.append(f"- {rel} {{{props}}}")

            categories = session.execute_read(
                lambda tx: [r["name"] for r in tx.run("MATCH (c:Category) RETURN c.name AS name ORDER BY name")]
            )
            areas = session.execute_read(
                lambda tx: [r["name"] for r in tx.run("MATCH (a:Area) RETURN a.name AS name ORDER BY name")]
            )
            specialties = session.execute_read(
                lambda tx: [r["name"] for r in tx.run("MATCH (s:Specialty) RETURN s.name AS name ORDER BY name")]
            )

            lines.append(f"\nKnown Category values (use EXACTLY these strings): {categories}")
            lines.append(f"Known Area values (use EXACTLY these strings): {areas}")
            lines.append(
                f"Known Specialty values -- what a place is FAMOUS FOR, e.g. 'good filter coffee near X' "
                f"or 'places famous for croissants' (use EXACTLY these strings): {specialties}"
            )
            lines.append(
                "\nEvery Place also carries a things_to_try property -- a list of specific, exact menu items "
                "pulled directly from reviews (e.g. 'nutella creme caramel coffee'). Free text, not a closed "
                "vocabulary like Specialty -- never filter/query on it, only surface it once a place is already "
                "identified by other means."
            )

    return "\n".join(lines)


if __name__ == "__main__":
    print(get_schema_context())
