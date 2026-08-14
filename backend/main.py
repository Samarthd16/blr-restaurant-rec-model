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
from query_intent import QueryIntent, build_intent_system_prompt, intent_to_cypher, parse_intent

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
    # Conversation memory, tracked client-side and echoed back each turn --
    # the backend is otherwise stateless per request. Used only to steer
    # follow-up suggestions away from ground already covered (never to
    # filter the actual answer -- a repeated user question still gets
    # answered normally).
    seen_places: list[str] = []
    asked_questions: list[str] = []


class PlaceResult(BaseModel):
    name: str
    distance_km: float | None = None
    rating: float | None = None
    user_rating_count: int | None = None
    things_to_try: list[str] = []


class PlacePairResult(BaseModel):
    place_a: str
    place_b: str
    distance_km: float


class GraphNode(BaseModel):
    id: str
    label: str
    # "reference" is visually distinguished (bigger, accent-colored) as the
    # hub of the snippet -- everything else is drawn around it.
    type: str  # "reference" | "place" | "area" | "category" | "specialty"


class GraphEdge(BaseModel):
    source: str
    target: str
    type: str  # "ADJACENT_TO" | "LOCATED_IN" | "IN_CATEGORY" | "FAMOUS_FOR" | "NEAR"
    label: str | None = None


class GraphSnippet(BaseModel):
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []


class ChatResponse(BaseModel):
    answer: str
    suggestions: list[str] = []
    # Distinct place names surfaced in this answer -- the frontend folds
    # these into seen_places for the next request.
    place_names: list[str] = []
    # Structured version of the same data in `answer` -- lets the frontend
    # render a proper card (gold star for rating, pill-styled things_to_try)
    # instead of parsing the plain-text string. `answer` is kept as the
    # primary text (used by the copy-to-clipboard button) for shapes without
    # a clean card representation (area lists, error messages).
    places: list[PlaceResult] = []
    # Separate shape for near_each_other results -- two places per row, no
    # rating/things_to_try, so it doesn't fit PlaceResult.
    place_pairs: list[PlacePairResult] = []
    # Small illustrative subgraph of the actual nodes/edges that produced
    # this answer -- not the full knowledge graph, just this query's slice
    # of it. Static (no coordinates), the frontend does its own layout.
    graph: GraphSnippet = GraphSnippet()


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

    print(f"\n[chat] Q: {req.question}")
    print(f"[chat] intent: {intent.model_dump()}")
    print(f"[chat] cypher: {cypher}")
    print(f"[chat] params: {params}")

    try:
        results = run_cypher(cypher, params)
    except ServiceUnavailable:
        # Most common cause: Neo4j Aura free tier auto-pauses after
        # inactivity. Alert the owner (cooldown-limited, see alerts.py) and
        # give the user a clear, honest message instead of a generic
        # "something went wrong."
        send_neo4j_down_alert()
        return ChatResponse(answer=NEO4J_DOWN_MESSAGE)

    print(f"[chat] {len(results)} result(s)")

    if not results and intent.relationship == "near_reference_place" and intent.reference_place_name:
        results, answer_override = retry_near_reference_place(intent, params)
        if answer_override:
            return ChatResponse(answer=answer_override, suggestions=[])

    seen_places = set(req.seen_places)
    asked_questions = set(req.asked_questions)
    return ChatResponse(
        answer=format_answer(results),
        suggestions=generate_suggestions(intent, results, seen_places, asked_questions),
        place_names=extract_place_names(results),
        places=extract_places(results),
        place_pairs=extract_place_pairs(results),
        graph=extract_graph_snippet(intent, results),
    )


def extract_places(results: list[dict]) -> list[PlaceResult]:
    """Structured per-place data for card rendering -- parallels
    format_answer()'s text version but keeps fields separate instead of
    baking them into one string, so the UI can style rating/things_to_try
    distinctly rather than parsing plain text. Only produced for the two
    shapes that actually carry rating/things_to_try (near_reference_place's
    "suggestion" rows, and the plain-filter "name" rows) -- area lists and
    place-pairs fall back to the plain-text answer on the frontend."""
    if not results:
        return []

    first = results[0]
    if "suggestion" in first:
        return [
            PlaceResult(
                name=r["suggestion"],
                distance_km=r.get("distance_km"),
                rating=r.get("rating"),
                user_rating_count=r.get("user_rating_count"),
                things_to_try=r.get("things_to_try") or [],
            )
            for r in results
        ]
    if "name" in first:
        return [
            PlaceResult(
                name=r["name"],
                rating=r.get("rating"),
                user_rating_count=r.get("user_rating_count"),
                things_to_try=r.get("things_to_try") or [],
            )
            for r in results
        ]
    return []


def extract_graph_snippet(intent: QueryIntent, results: list[dict]) -> GraphSnippet:
    """Builds the small subgraph that actually produced this answer, from
    data already in hand -- no extra Neo4j round-trip. Not the whole graph,
    just this query's slice of it: the reference place and its ADJACENT_TO
    neighbors, or the shared Area/Category/Specialty node a filtered list
    matched against, whichever applies to this result shape."""
    if not results:
        return GraphSnippet()

    nodes: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []

    def node(node_id: str, label: str, node_type: str) -> str:
        if node_id not in nodes:
            nodes[node_id] = GraphNode(id=node_id, label=label, type=node_type)
        return node_id

    first = results[0]

    if "suggestion" in first:
        ref_name = first.get("reference") or intent.reference_place_name
        ref_id = node(f"place:{ref_name}", ref_name, "reference")
        for r in results:
            place_id = node(f"place:{r['suggestion']}", r["suggestion"], "place")
            dist_m = round(r["distance_km"] * 1000)
            edges.append(GraphEdge(source=ref_id, target=place_id, type="ADJACENT_TO", label=f"{dist_m}m"))

    elif "place_a" in first:
        for r in results:
            a_id = node(f"place:{r['place_a']}", r["place_a"], "place")
            b_id = node(f"place:{r['place_b']}", r["place_b"], "place")
            dist_m = round(r["distance_km"] * 1000)
            edges.append(GraphEdge(source=a_id, target=b_id, type="ADJACENT_TO", label=f"{dist_m}m"))

    elif "area" in first and "distance_km" in first:
        origin_id = node(f"area:{intent.area}", intent.area, "reference")
        for r in results:
            area_id = node(f"area:{r['area']}", r["area"], "area")
            edges.append(GraphEdge(source=origin_id, target=area_id, type="NEAR", label=f"{r['distance_km']:.1f}km"))

    elif "name" in first:
        # The shared node(s) every place in this list matched against --
        # that's the actual graph structure behind a plain filter query.
        hub_ids = []
        if intent.area:
            hub_ids.append((node(f"area:{intent.area}", intent.area, "area"), "LOCATED_IN"))
        if intent.category:
            hub_ids.append((node(f"category:{intent.category}", intent.category, "category"), "IN_CATEGORY"))
        if intent.specialty:
            hub_ids.append((node(f"specialty:{intent.specialty}", intent.specialty, "specialty"), "FAMOUS_FOR"))
        for r in results[:8]:  # cap so the diagram stays legible
            place_id = node(f"place:{r['name']}", r["name"], "place")
            for hub_id, edge_type in hub_ids:
                edges.append(GraphEdge(source=place_id, target=hub_id, type=edge_type))

    return GraphSnippet(nodes=list(nodes.values()), edges=edges)


def extract_place_pairs(results: list[dict]) -> list[PlacePairResult]:
    """Structured version of the near_each_other shape -- same reasoning as
    extract_places(), just a different row shape (two places, no rating/
    things_to_try, since a pair isn't "about" either place individually)."""
    if not results or "place_a" not in results[0]:
        return []
    return [
        PlacePairResult(place_a=r["place_a"], place_b=r["place_b"], distance_km=r["distance_km"])
        for r in results
    ]


def extract_place_names(results: list[dict]) -> list[str]:
    """Distinct place names appearing anywhere in a result set, regardless of
    shape. The frontend folds these into seen_places for its next request --
    this is what lets generate_suggestions() steer away from places already
    surfaced instead of bouncing between the same tight cluster forever."""
    names: set[str] = set()
    for r in results:
        for key in ("suggestion", "place_a", "place_b", "name", "reference"):
            if r.get(key):
                names.add(r[key])
    return sorted(names)


def retry_near_reference_place(intent: QueryIntent, params: dict) -> tuple[list[dict], str | None]:
    """The first near_reference_place query came back empty. Rather than just
    reporting failure, figure out WHY before giving up -- most often it's the
    tier/category/specialty filter excluding every neighbor, not that the
    reference place itself is unresolved (ADJACENT_TO is capped at 500m and
    top-4 neighbors, so a real "no close neighbors recorded" case does
    happen). Not another LLM call -- same deterministic-Cypher philosophy as
    intent_to_cypher(), just retried once with filters dropped."""
    resolved = run_cypher(
        "CALL db.index.fulltext.queryNodes('place_name_fulltext', $ref_query) "
        "YIELD node, score RETURN node.name AS name ORDER BY score DESC LIMIT 1",
        {"ref_query": params["ref_query"]},
    )
    if not resolved:
        print(f"[chat] retry: no place matched '{intent.reference_place_name}'")
        return [], None  # let format_answer's generic empty-result message stand

    relaxed_cypher = (
        "CALL db.index.fulltext.queryNodes('place_name_fulltext', $ref_query) "
        "YIELD node AS ref, score "
        "WITH ref, score ORDER BY score DESC LIMIT 1 "
        "MATCH (ref)-[r:ADJACENT_TO]-(p:Place) "
        "RETURN ref.name AS reference, score AS reference_match_confidence, "
        "p.name AS suggestion, p.rating AS rating, p.user_rating_count AS user_rating_count, "
        "p.things_to_try AS things_to_try, r.distance_km AS distance_km "
        "ORDER BY r.distance_km LIMIT $limit"
    )
    relaxed_params = {"ref_query": params["ref_query"], "limit": params.get("limit", 10)}
    results = run_cypher(relaxed_cypher, relaxed_params)

    name = resolved[0]["name"]
    if results:
        print(f"[chat] retry: dropped tier/category/specialty filters, found {len(results)} neighbor(s) of {name}")
        return results, None

    print(f"[chat] retry: {name} resolved but has no ADJACENT_TO neighbors in the data")
    return [], f"I found {name}, but it doesn't have any nearby places recorded in the current dataset."


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
            rating = r.get("rating")
            rating_suffix = f" — {rating}★" if rating else ""
            things = r.get("things_to_try") or []
            try_suffix = f" — try: {', '.join(things[:3])}" if things else ""
            lines.append(f"- {r['suggestion']} ({dist_m}m away){rating_suffix}{try_suffix}")
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
            things = r.get("things_to_try") or []
            if things:
                suffix += f" — try: {', '.join(things[:3])}"
            lines.append(f"- {r['name']}{suffix}")
        return "\n".join(lines)

    return str(results)


def _probe_has_results(candidate_intent: QueryIntent) -> bool:
    """Existence check for a candidate follow-up question -- same
    deterministic Cypher path a real query would take, just capped to 1 row
    so it's cheap. A suggestion is only ever shown to the user after this
    passes, so clicking a chip can never dead-end into "couldn't find
    anything" the way a blind-guessed suggestion could."""
    probe = candidate_intent.model_copy(update={"limit": 1})
    cypher, params = intent_to_cypher(probe)
    try:
        return len(run_cypher(cypher, params)) > 0
    except ServiceUnavailable:
        return False


def generate_suggestions(
    intent: QueryIntent,
    results: list[dict],
    seen_places: set[str] | None = None,
    asked_questions: set[str] | None = None,
) -> list[str]:
    """Follow-up questions, not another LLM call -- built from values already
    known (the parsed intent, the top result), same reasoning as
    format_answer(). Each candidate is built as a real QueryIntent and
    verified against the graph with _probe_has_results() before being
    offered -- candidates are listed most specific first, so a broader
    fallback (e.g. "top-rated in the area" instead of "near this exact
    place") gets a chance if the specific one comes back empty.

    seen_places/asked_questions are conversation memory from the client:
    without them, "near X" style candidates always anchor on the current
    top result, and in a tightly-connected cluster (everything near
    everything else within a couple hundred metres) that oscillates between
    the same handful of places turn after turn. Anchoring on the first
    not-yet-seen place instead, and dropping any candidate whose exact text
    was already asked, breaks the loop and pushes the conversation outward."""
    if not results:
        return []

    seen_places = seen_places or set()
    asked_questions = asked_questions or set()
    first = results[0]
    candidates: list[tuple[QueryIntent, str]] = []

    def add(candidate_intent: QueryIntent, text: str) -> None:
        candidates.append((candidate_intent, text))

    def first_unseen(key: str) -> str:
        return next((r[key] for r in results if r.get(key) not in seen_places), first[key])

    if "suggestion" in first:
        ref = first.get("reference") or intent.reference_place_name
        anchor = first_unseen("suggestion")
        add(
            QueryIntent(relationship="near_reference_place", reference_place_name=anchor),
            f"What's near {anchor}?",
        )
        if intent.sort_by != "rating":
            add(
                QueryIntent(relationship="near_reference_place", reference_place_name=ref, sort_by="rating"),
                f"What's the top-rated place near {ref}?",
            )
        if intent.area:
            add(
                QueryIntent(relationship="none", area=intent.area, sort_by="rating"),
                f"What's the top-rated place in {intent.area}?",
            )

    elif "place_a" in first:
        anchor = first_unseen("place_a")
        add(
            QueryIntent(relationship="near_reference_place", reference_place_name=anchor),
            f"What's near {anchor}?",
        )
        if intent.area:
            add(
                QueryIntent(relationship="expand_to_adjacent_areas", area=intent.area),
                f"What areas are near {intent.area}?",
            )
            add(
                QueryIntent(relationship="none", area=intent.area, sort_by="rating"),
                f"What's the top-rated place in {intent.area}?",
            )

    elif "area" in first and "distance_km" in first:
        add(
            QueryIntent(relationship="none", area=first["area"], sort_by="rating"),
            f"What's the top-rated place in {first['area']}?",
        )

    elif "name" in first:
        anchor = first_unseen("name")
        add(
            QueryIntent(relationship="near_reference_place", reference_place_name=anchor),
            f"What's near {anchor}?",
        )
        if intent.specialty and intent.sort_by != "rating":
            add(
                QueryIntent(relationship="none", specialty=intent.specialty, sort_by="rating"),
                f"What are the top-rated places famous for {intent.specialty}?",
            )
        if intent.category and intent.sort_by != "rating":
            add(
                QueryIntent(relationship="none", category=intent.category, sort_by="rating"),
                f"What are the top-rated {intent.category}?",
            )
        if intent.area:
            add(
                QueryIntent(relationship="expand_to_adjacent_areas", area=intent.area),
                f"What areas are near {intent.area}?",
            )
            if intent.sort_by != "rating":
                add(
                    QueryIntent(relationship="none", area=intent.area, sort_by="rating"),
                    f"What's the top-rated place in {intent.area}?",
                )

    # Unconditional last resort: no area/category/specialty/tier filter at
    # all, just "top-rated overall" -- can only ever come back empty if the
    # graph has zero Place nodes. Suggestions don't have to relate to the
    # current answer; a context-specific candidate can fail for reasons that
    # have nothing to do with a bug (an isolated place with no recorded
    # neighbors, an area with no NEAR edges, etc.), and when every other
    # candidate above dries up, this guarantees the user is never left with
    # zero suggestions to click.
    add(QueryIntent(relationship="none", sort_by="rating"), "What are the top-rated places overall?")

    suggestions: list[str] = []
    for candidate_intent, text in candidates:
        if text in asked_questions:
            continue
        if _probe_has_results(candidate_intent):
            suggestions.append(text)
        if len(suggestions) == 3:
            break
    return suggestions
