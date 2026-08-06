"""
One-time cleanup after swapping the NEAR/ADJACENT_TO naming (Area-to-Area is
now NEAR, Place-to-Place is now ADJACENT_TO). MERGE in load_graph.py created
the newly-named relationships but never removed the old ones from before the
swap, so both now exist side by side. This deletes the leftover wrong-typed
ones: ADJACENT_TO between two Areas, and NEAR between two Places.

Safe to run more than once -- once the wrong-typed relationships are gone,
re-running finds nothing to delete.
"""

import os

from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

URI = os.environ["NEO4J_URI"]
AUTH = (os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"])


def main():
    with GraphDatabase.driver(URI, auth=AUTH) as driver:
        with driver.session() as session:
            result = session.run(
                """
                MATCH (:Area)-[r:ADJACENT_TO]-(:Area)
                DELETE r
                RETURN count(r) AS deleted
                """
            )
            print(f"Deleted {result.single()['deleted']} stale Area-Area ADJACENT_TO edges.")

            result = session.run(
                """
                MATCH (:Place)-[r:NEAR]-(:Place)
                DELETE r
                RETURN count(r) AS deleted
                """
            )
            print(f"Deleted {result.single()['deleted']} stale Place-Place NEAR edges.")


if __name__ == "__main__":
    main()