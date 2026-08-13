"""
Natural-language -> graph context, end to end.

Two-stage pipeline (see query_intent.py):
  1. NL question -> structured QueryIntent (LLM, schema fed in live from
     graph_schema.py -- not hand-maintained, stays accurate as the graph
     changes).
  2. QueryIntent -> Cypher (deterministic Python templating, no LLM).

Two independent safety layers before anything runs against the DB, even
though intent_to_cypher() only ever builds read-shaped queries by
construction:
  1. Keyword blocklist on the generated query text.
  2. Executed via Neo4j's execute_read() transaction function, which the
     server itself rejects a write against.
"""

import json
import os
import re

from dotenv import load_dotenv
from neo4j import GraphDatabase
from openai import OpenAI

from query_intent import build_intent_system_prompt, intent_to_cypher, parse_intent

load_dotenv()

NEO4J_URI = os.environ["NEO4J_URI"]
NEO4J_AUTH = (os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"])

openai_client = OpenAI()  # reads OPENAI_API_KEY from env

WRITE_KEYWORDS = re.compile(
    r"\b(CREATE|MERGE|DELETE|SET|REMOVE|DROP|DETACH)\b", re.IGNORECASE
)


def run_cypher(query: str, params: dict) -> list[dict]:
    if WRITE_KEYWORDS.search(query):
        raise ValueError(f"Refusing to run non-read-only query: {query}")

    # connection_timeout caps the initial connection attempt; max_transaction_retry_time
    # caps the driver's own transient-error retry loop (default 30s, with
    # exponential backoff) -- without both, a paused Aura instance (free tier
    # auto-pauses after inactivity) can take 30+ seconds to finally raise
    # ServiceUnavailable, instead of failing fast.
    with GraphDatabase.driver(
        NEO4J_URI, auth=NEO4J_AUTH, connection_timeout=10, max_transaction_retry_time=5
    ) as driver:
        with driver.session() as session:
            # execute_read (not session.run) -- Neo4j itself rejects a write
            # attempted inside a read transaction, a second enforcement
            # layer independent of the keyword check above.
            records = session.execute_read(lambda tx: list(tx.run(query, params)))
            return [dict(r) for r in records]


def ask(question: str, system_prompt: str | None = None):
    print(f"\nQ: {question}")

    intent = parse_intent(openai_client, question, system_prompt=system_prompt)
    print(f"Intent: {intent.model_dump()}")

    cypher, params = intent_to_cypher(intent)
    print(f"Cypher: {cypher}")
    print(f"Params: {params}")

    results = run_cypher(cypher, params)
    print(f"Context ({len(results)} rows):")
    print(json.dumps(results, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    # introspect the schema once, reuse across all questions in this run
    system_prompt = build_intent_system_prompt()

    # ask("What bars in Indiranagar are near each other?", system_prompt)
    # ask("What are the top rated S-tier cafes?", system_prompt)
    # ask("Which areas are near Koramangala?", system_prompt)
    ask("What restaurant do you suggest to visit for dessert after drinking at toit in Indiranagar?", system_prompt)
