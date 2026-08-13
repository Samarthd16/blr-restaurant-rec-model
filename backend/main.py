"""
FastAPI service backing the Cafe Hopper Guide frontend. Wraps the existing
NL -> intent -> Cypher -> Neo4j pipeline (app/nl_to_cypher.py,
app/query_intent.py) behind a single POST /chat endpoint.

Run from backend/: uvicorn main:app --reload
"""

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "app"))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from neo4j.exceptions import ServiceUnavailable
from pydantic import BaseModel

from alerts import send_neo4j_down_alert
from nl_to_cypher import openai_client, run_cypher
from query_intent import build_intent_system_prompt, intent_to_cypher, parse_intent

# Introspected once at startup (schema rarely changes mid-run), not on every
# request -- same reasoning as the CLI loop in nl_to_cypher.py.
_system_prompt: str | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _system_prompt
    try:
        _system_prompt = build_intent_system_prompt()
    except ServiceUnavailable:
        # Don't let a paused/unreachable Neo4j instance crash the entire
        # server at boot -- leave _system_prompt as None and let /chat
        # retry building it lazily on each request until Neo4j is back up,
        # rather than requiring a manual restart once it's resumed.
        print("Neo4j unreachable at startup -- will retry lazily on the next chat request.")
        send_neo4j_down_alert()
    yield


app = FastAPI(title="Cafe Hopper Guide API", lifespan=lifespan)

# Localhost (any port -- Vite shifts 5173/5174/... if the default is busy)
# always allowed for dev. Any *.vercel.app subdomain always allowed too --
# Vercel mints a NEW preview URL per branch/deployment (e.g.
# blr-restaurant-rec-git-<hash>-<team>.vercel.app), so pinning to one exact
# origin via FRONTEND_ORIGIN breaks on every push. FRONTEND_ORIGIN still
# exists for a future custom domain that won't match the regex.
_production_origins = [
    origin.strip()
    for origin in os.environ.get("FRONTEND_ORIGIN", "").split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://localhost:\d+|https://[\w-]+\.vercel\.app",
    allow_origins=_production_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    question: str


class ChatResponse(BaseModel):
    answer: str


NEO4J_DOWN_MESSAGE = "The knowledge graph instance is down. Please try again later."


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    global _system_prompt

    if _system_prompt is None:
        # Startup's schema introspection failed (or hasn't run yet) --
        # retry here so the app self-heals once Neo4j comes back, instead
        # of staying broken until someone manually restarts the server.
        try:
            _system_prompt = build_intent_system_prompt()
        except ServiceUnavailable:
            send_neo4j_down_alert()
            return ChatResponse(answer=NEO4J_DOWN_MESSAGE)

    intent = parse_intent(openai_client, req.question, system_prompt=_system_prompt)
    cypher, params = intent_to_cypher(intent)

    try:
        results = run_cypher(cypher, params)
    except ServiceUnavailable:
        # Most common cause: Neo4j Aura free tier auto-pauses after
        # inactivity. Alert the owner (cooldown-limited, see alerts.py) and
        # give the user a clear, honest message instead of a generic
        # "something went wrong."
        send_neo4j_down_alert()
        return ChatResponse(answer=NEO4J_DOWN_MESSAGE)

    return ChatResponse(answer=format_answer(results))


def format_answer(results: list[dict]) -> str:
    """Deterministic templating, not another LLM call -- fast, reliable,
    and matches the intent_to_cypher() philosophy of using LLM only where
    genuinely needed (understanding the question), not for formatting."""
    if not results:
        return "I couldn't find anything matching that in the current dataset."

    first = results[0]

    if "suggestion" in first:
        ref = first.get("reference", "that place")
        lines = [f"Near {ref}, you could try:"]
        for r in results:
            dist_m = round(r["distance_km"] * 1000)
            lines.append(f"- {r['suggestion']} ({dist_m}m away)")
        return "\n".join(lines)

    if "place_a" in first:
        lines = ["Places near each other:"]
        for r in results:
            dist_m = round(r["distance_km"] * 1000)
            lines.append(f"- {r['place_a']} and {r['place_b']} ({dist_m}m apart)")
        return "\n".join(lines)

    if "area" in first and "distance_km" in first:
        lines = ["Nearby areas:"]
        for r in results:
            lines.append(f"- {r['area']} ({r['distance_km']:.1f}km away)")
        return "\n".join(lines)

    if "name" in first:
        lines = ["Here's what I found:"]
        for r in results:
            rating = r.get("rating")
            count = r.get("user_rating_count")
            suffix = f" — {rating}★ ({count} ratings)" if rating else ""
            lines.append(f"- {r['name']}{suffix}")
        return "\n".join(lines)

    return str(results)
