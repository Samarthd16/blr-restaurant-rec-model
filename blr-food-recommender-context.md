# Bengaluru Food-Spot Recommender with Reachability Intelligence — Full Context

*Single source of truth for the whole project: what it is, every decision made, and what's still open.*

---

## 1. The concept

A recommendation system for Bengaluru food spots. A user gives a **natural-language request +
a profile**, and the system returns **ranked recommendations** by combining three signals:

- **Semantic** — matching vibe/intent ("quiet, good for laptop work") against embedded review text.
- **Structured** — hard filters (price, area, rating, cuisine, dietary needs).
- **Accessibility** — how easy each candidate is to reach from the user's home location.

Example query:
> "Quiet cafe in Indiranagar, good for laptop work, under ₹500, easy to reach from Koramangala."

Final architecture: **GraphRAG** — a vector store (semantic) + a knowledge graph (relationships)
working together, joined by `place_id`, their results fused into one ranking, then scored for reachability.

---

## 2. Goals (all weighted equally)

1. **Get hired** — showcase agentic AI, GraphRAG/hybrid retrieval, and a rigorous evaluation harness.
2. **Genuinely useful** — a tool actually worth using in Bengaluru.
3. **Skill-building** — RAG, graph retrieval, LangGraph agents, RAGAS evaluation.

**Tie-breaker when goals conflict:** objective, impressive **evaluation** wins (the accessibility layer
gives objectively checkable numbers).

---

## 3. Build philosophy (prevents scope creep and stalls)

- **Graph-first build order (redefined 2026-08-02).** Originally planned as pgvector-first, then
  graph-second. Redefined to build the Neo4j knowledge graph first — embeddings are generated only
  as needed for graph-internal use (e.g. ranking `SIMILAR_TO` candidates), not gated behind a
  complete standalone pgvector product first.
- **Never half-broken.** Each piece should be independently useful/testable as it's built.
- **Respect the scope firewall** (below). Check the OUT list before adding anything.

---

## 4. Scope

### In scope (v1)
- All food places: cafes, restaurants, bars, bakeries, street food.
- Recommendation + reachability only.
- Profile-driven personalization (home location, dietary prefs, budget, taste) — passed per request.
- Bengaluru only.
- Backend + simple functional UI.

### Out of scope (v1) — the firewall
- NO bookings / reservations.
- NO live info (wait times, open-now) — stored hours only.
- NO auth / login — profile passed per request; auth is a stretch goal.
- NO other cities.
- NO mobile app.

---

## 5. Data decisions (LOCKED)

| Need | Source | Notes |
|---|---|---|
| Restaurant data + reviews | **Self-built dataset via Google Places API** | One-time ingestion across BLR neighborhoods; fetch details + reviews; dedup; store in both stores. Known limit: ~5 reviews/place (acceptable for v1). NOT queried live per request (saves quota). Filtered to `user_rating_count >= MIN_RATING_COUNT` (`.env`, currently 500, added 2026-08-02) — cuts low-confidence/obscure places; chosen by eyeballing the bucket distribution (`plot_review_count_buckets.py`), not a fixed rule. Note this is Google's *total* rating count (popularity signal), unrelated to the ~5-review text cap above — raising this threshold does not get more review text per place. |
| Accessibility (driving + transit) | **Google Directions/Routes API** | Live, per-request, for final candidates only (quota-smart). |
| ~~Scraping Zomato/Swiggy~~ | **Rejected** | ToS grey area, fragile, and a red flag for the regulated employers being targeted. Building our own dataset is cleaner and a stronger interview story. |
| Cafe-hopping / itinerary pairing signal (stretch) | **Scraped food blogs/listicles** (not Zomato/Swiggy) | Human-curated "best cafe crawl in X" posts encode implicit similarity/pairing signal Google doesn't expose. Deferred — needs name-matching back to `place_id`; not the Zomato/Swiggy ToS concern since it's editorial content, not a competitor's structured business data. |

Paid APIs OK within free-tier limits. Quota is a real design constraint.

---

## 6. Architecture

### 6.1 Two stores, joined by `place_id`

The key mental model: pgvector and Neo4j hold **two different kinds of knowledge about the same places**.
A query uses **both** — each for what it's good at.

```
pgvector (AlloyDB)                    Neo4j (graph)
place_id: 101                         (Place {id:101, name:"Toit"})
  name, area, price, amenities,         ├─LOCATED_IN→(Area:"Indiranagar")
  rating, lat, lng, hours,              ├─HAS_VIBE→(Vibe:"Lively")
  review_text, review_embedding         ├─FAMOUS_FOR→(Specialty:"Craft Beer")
                                        ├─SUITABLE_FOR_DIET→(Diet:"Vegetarian")
                                        ├─(Area)─ADJACENT_TO→(Area)
                                        └─SIMILAR_TO→(Place:{id:118})
```

- **pgvector** = the semantic lens ("which places *feel* like what the user described?").
- **Neo4j** = the relationship lens ("which places are *connected* to what the user wants?").
- **`place_id`** = the join key linking the two.

### 6.2 Query flow (final GraphRAG state)

```
NL query + user profile
   │
[Parse]  LLM → semantic intent + structured filters + relationship cues
   │
   ├─► [Semantic retrieval] pgvector: filter-then-vector-rank → place_ids
   │        (mirrors the developer's Contract-to-Cash opp_id filter-then-rank pattern)
   │
   └─► [Graph retrieval] Neo4j: traverse (similar-to, adjacent-area,
            vibe/specialty/diet match) → place_ids
   │
[Fuse]  combine the two place_id sets via Reciprocal Rank Fusion (RRF)
   │
[Accessibility scoring]  Directions API for the top fused candidates only
   │
[Rank & explain]  combined score; the graph path becomes the "why"
   │
Ranked recommendations + explanations
```

### 6.3 How the two stores work together (the mechanism)

Every place lives in BOTH stores, linked by `place_id`. On a query:
1. **pgvector** returns place_ids whose reviews semantically match the vibe.
2. **Neo4j** returns place_ids connected via relationships (similar-to, adjacent-area, shared vibe/specialty/diet).
3. **Fusion** combines the two ID lists — places appearing in both rank highest; the rest merge via RRF.
   (This is the same fusion concept as hybrid dense+sparse search, applied to semantic + graph.)
4. Accessibility scoring + final ranking on the fused candidates.

### 6.4 Why GraphRAG — and the caution

The graph earns its complexity ONLY if genuinely traversed: similar-place recommendation,
adjacent-area expansion when nothing fits, and path-based explanations.
If the graph ends up only being queried like a table (filter by area/cuisine), that's over-engineering
and pgvector alone would be the honest choice. **Design the graph so its relationships are actually used.**
This is the test every candidate node/edge in §8.1 was run through — several were cut for failing it
(cuisine-pairing, amenities-as-nodes) even though they were on the original candidate list.

---

## 7. Build order (redefined 2026-08-02 — graph-first)

Originally sequenced as pgvector-first, then graph-second (see git history / prior version of this
doc if needed). Redefined: the knowledge graph is being designed and built first, since it's where
the open design questions currently are. Embeddings are built as needed to support graph edges
(e.g. ranking `SIMILAR_TO` candidates) rather than as a full standalone pgvector product first.

**Built and working end-to-end (2026-08-06)**
- Dataset: the original 50-place sample (5 BLR regions) merged with a full 211-place Indiranagar
  pull (all 6 search categories, deduped against the sample) — `backend/data/normalized_places.json`,
  160 places after the `MIN_RATING_COUNT` filter. Full-city ingestion (beyond Indiranagar) is still
  not done — see below.
- Mechanical graph layer fully loaded into Neo4j Aura: `Place` (+ `S`/`A`/`B` tier labels),
  `Area`, `Category` nodes; `LOCATED_IN`, `IN_CATEGORY`, `NEAR` (Area), `ADJACENT_TO` (Place) edges.
  See §8.1 for the schema, `backend/scripts/rebuild_graph.ps1` for the one-command rebuild pipeline
  (normalize → graph elements → adjacency → proximity → prune stale nodes → load).
- Full-text fuzzy index (`place_name_fulltext`, Lucene-backed) on `Place.name` — resolves a
  user-typo'd or slightly-off place name ("Toitt" → "Toit") via edit-distance search instead of
  exact/substring matching. Created idempotently in `load_graph.py`.
- **Query pipeline** — natural language question → answer, fully working. See new §13 for the
  detailed design. High-level: two-stage (LLM parses structured intent → deterministic Python
  templates build the Cypher, no freeform LLM-generated Cypher against the live DB), schema fed to
  the LLM via **live introspection** (`graph_schema.py`) rather than a hand-maintained description,
  and a small golden-set eval (`eval_intent.py`) for intent-parsing accuracy specifically — a first,
  narrow instance of the "evaluation early" principle (§2), not the full RAGAS harness yet.
- **LLM provider: OpenAI (`gpt-4o-mini`), not Anthropic/Vertex AI as originally planned** — switched
  after hitting an Anthropic billing wall (API credits are billed separately from a Claude.ai
  subscription) and the user having existing OpenAI credits. See §10 for the full tech-stack update.
- Basic frontend + backend shipped: a React/Vite/TypeScript chat UI ("Cafe Hopper Guide", working
  title) in `frontend/`, and a FastAPI service (`backend/main.py`, single `POST /chat` endpoint)
  wrapping the query pipeline. Answer formatting is currently **deterministic templating**, not an
  LLM synthesis pass — fast and hallucination-free, but mechanical phrasing; a natural upgrade later.
- Deployment scaffolding: `backend/Dockerfile` (for Railway — Vercel does NOT need Docker, it has
  native Vite support), CORS/API-URL wired via env vars (`FRONTEND_ORIGIN` on the backend,
  `VITE_API_BASE_URL` on the frontend) so local dev and production don't hardcode each other's URLs.
  `backend/.gitignore` added (`.env`, `.venv` excluded); `backend/data/` deliberately kept tracked in
  git — it represents real, already-spent Places API quota, not something to casually regenerate.

**A concrete data-quality finding worth knowing** — `Category` (search-match-based) is coarser than
it looks: a place can genuinely show up in multiple category searches even when it's not a strong
fit for all of them (Google's Text Search relevance is loose). Confirmed end-to-end: "tribal brew
daily" — primarily a coffee/breakfast spot — matched all of `breweries`, `cafes`, `coffee roasters`,
`coffee shops`, AND `dessert shops` during the original sweep, so it surfaces as a "dessert"
suggestion despite not being one. This is exactly the gap `Specialty`/`FAMOUS_FOR` (review-derived,
still pending) was always meant to close — `Category` is the cheap stand-in, not the precise version.
See §9 for this as a standing risk.

**Still to build**
- `Specialty` extraction pipeline (concrete plan, not yet started): (1) one vocabulary-discovery
  pass over all review text to find themes that recur across *multiple* places, not hand-invented;
  (2) per-place tagging against that closed vocabulary, resumable/incremental by `place_id` (same
  pattern as `fetch_area_details.py`); (3) load as `Specialty` nodes + `FAMOUS_FOR` edges, same
  `MERGE`-based loader shape as `Category`. At full-city scale, the per-place tagging step is where
  switching to OpenAI's Batch API (~50% cheaper, async) becomes worth it — not needed at current
  (160-place) volume.
- `Vibe` extraction — same treatment as `Specialty` above, not yet started. Expect only ~4-6 real
  categories to survive frequency clustering, most candidate tags will be one-off noise.
- `Diet` suitability: Places API's `servesVegetarianFood` field (if present) plus review extraction
  for finer categories (vegan, Jain, gluten-free) not covered by that field.
- `SIMILAR_TO`: filter-then-rank (structural candidates via shared `Area`/`Vibe`, then
  embedding-ranked) — needs `Vibe` to exist first, and an embedding-model decision (now that the
  LLM provider is OpenAI, `text-embedding-3-small` is the natural default, not yet decided).
- Real Directions/Routes-API travel time between Area centroids as an `Area NEAR` upgrade (still
  just a considered idea, not decided) — technically feasible since areas are a small bounded set,
  unlike per-user reachability which can't be precomputed.
- pgvector semantic retrieval layer — still fully pending. The current working system is **graph-only
  retrieval**, not the fused GraphRAG described in §6.1/6.2; those sections describe the target end
  state, not what's running today.
- Accessibility scoring (Directions/Routes API), live per-request only, final candidates only.
- Fusion of semantic + graph candidate sets (RRF), graph-path explanations.
- Full RAGAS-based evaluation harness (beyond the narrow intent-accuracy eval already built).
- LLM-based answer synthesis (replacing the current deterministic templating) for more natural,
  explained responses in the chat UI.
- Full-city ingestion beyond the current sample + Indiranagar (neighborhood-sweep approach already
  prototyped and rejected as premature — see conversation; revisit once graph/query work is validated).

**Stretch goals (post-v1):** auth/multi-user, more cities, richer review corpus, live status,
cafe-hopping/itinerary pairing edges (via blog scraping, §5 — partially already covered mechanically
by `ADJACENT_TO`, see §8.1).

---

## 8. Still to be designed (OPEN — decide collaboratively, don't assume)

### 8.1 Graph schema — LOCKED (2026-08-02)

**Nodes:**
- `Place` — core entity. Properties: place_id, name, rating, price, lat/lng, hours, `tier`
  (added 2026-08-02 — B/A/S by `user_rating_count`: 500+/1000+/2500+, derived after the
  `MIN_RATING_COUNT` filter so every remaining place lands in one of the three, never below).
  `Place.name` also has a full-text fuzzy index (`place_name_fulltext`, Lucene-backed, added
  2026-08-06) — lets the query pipeline resolve a user-typo'd place name via edit-distance search
  instead of exact/substring matching; see §13.
- `Area` — neighborhood, taken from known area label (not address-parsed — see ingestion note below).
- `Vibe` — atmosphere/mood (e.g. Cozy, Lively, WorkFriendly). Closed vocabulary, LLM-extracted from
  reviews, kept small deliberately so nodes are shared across places (open-ended tags would produce
  disconnected one-off nodes and defeat traversal).
- `Specialty` — what a place is known for (e.g. Matcha, Desserts, Filter Coffee). Same closed-vocabulary
  treatment as `Vibe`, bucketed into categories rather than raw dish names (longer tail than Vibe,
  needs coarser buckets to stay traversable).
- `Diet` — dietary suitability (Vegetarian, Vegan, Jain, Gluten-Free).
- `Category` (added 2026-08-02) — coarse, mechanical "type of food" (cafe, coffee shop, dessert shop,
  bar, brewery, coffee roaster), taken directly from which search category found each place — zero
  extra cost, no LLM. NOT the same as `Specialty` above: `Specialty` is the finer-grained, LLM-derived
  version (matcha specifically, not just "coffee shop"), still pending. `Category` is the cheap
  version, built and loaded now; `Specialty` will supplement it later, not replace it.

**Edges:**
- `Place -[LOCATED_IN]-> Area`
- `Place -[IN_CATEGORY]-> Category` (added 2026-08-02) — one per category a place matched during search.
- `Area -[NEAR]-> Area` — coarse neighborhood adjacency, computed from area centroids (avg lat/lng
  of places per area) + top-K nearest; real travel-time upgrade considered (see §7), not yet built.
  Used for search-expansion fallback ("nothing fits here → expand to nearby areas").
- `Place -[HAS_VIBE]-> Vibe`
- `Place -[FAMOUS_FOR]-> Specialty`
- `Place -[SUITABLE_FOR_DIET]-> Diet`
- `Place -[SIMILAR_TO]-> Place` — filter-then-rank (structural candidates, then embedding-ranked).
- `Place -[ADJACENT_TO]- Place` (added 2026-08-02, undirected) — real walking-distance proximity
  between individual places (haversine, capped at 500m AND top-4 per place — the distance cap alone
  wasn't enough once dense areas like Indiranagar were added; ~200 places in one small area made a
  pure 1km threshold connect nearly everything to everything, so top-K was added to keep the graph
  meaningful in dense clusters, not just sparse ones). Different from Area `NEAR`: area-level
  adjacency is coarse and can be wrong at area boundaries (two places in the same large Area can be
  3km apart; two places in different-but-adjacent Areas can be next door). Also doubles as a free,
  mechanical proxy for the cafe-hopping/itinerary signal — no blog scraping needed, just coordinates
  in hand.

  (Naming note: `NEAR` = Area-to-Area, `ADJACENT_TO` = Place-to-Place — the reverse of the more
  obvious mapping, deliberately chosen this way.)

**Cut, deliberately (failed the "is this genuinely traversed" test in §6.4):**
- `Cuisine` node + `PAIRS_WITH` edge — Google's `types` field is too generic to be real cuisine
  data, and 50 cafes is too small a sample for statistically meaningful cuisine-pairing patterns.
  Revisit once the dataset is city-scale.
- `Amenity` as a node (e.g. parking, outdoor seating) — single-place boolean facts, never actually
  traversed multi-hop. Belongs as a `Place` property/column, not a graph node.
- `Brand`/`Chain` and `Reviewer` nodes — speculative at 50-place scale; likely near-zero real overlap
  to traverse.
- Reachability/travel-time to a user's home as a graph edge — not precomputable (home location is
  unbounded per request); stays a live Directions/Routes API call at query time.

### 8.2 Other open items

1. **Ingestion pipeline** — dual-store population; dedup; enrichment (vibe/specialty extraction,
   area adjacency, similarity edges); keyed by `place_id`. Note: `Area` is populated from the
   neighborhood used to find the place during search (already captured in the sample dataset as
   `_sample_area`), not parsed from Google's messy `formattedAddress` strings.
2. **Data model** — pgvector table columns, embedding model + dimensionality, Neo4j schema.
3. **Agent architecture** — single-agent-with-tools vs multi-agent supervisor. Right-size it
   (don't over-agent). How the LLM parses NL → semantic intent + filters + relationship cues.
4. **Retrieval + fusion** — traversal design; RRF fusion of semantic + graph candidate sets.
5. **Accessibility scoring** — final-candidates-only vs precompute; the scoring formula.
6. **Evaluation plan** — golden set design; RAGAS metrics (faithfulness, context precision/recall,
   answer relevancy) for recommendation quality; objective accuracy metrics for the accessibility
   layer (travel times/routes are checkable → hard numbers). **THE DIFFERENTIATOR — design early.**
7. **UI** — minimal functional web UI.
8. **User profile schema** — the per-request profile object shape.

---

## 9. Risks & unknowns

- **API quota** (Places + Directions free tiers) — mitigate via one-time dataset build + scoring only final candidates.
- **Shallow review corpus** (~5 reviews/place from Places) — acceptable for v1; could supplement later.
- **Bengaluru transit data quality** via Directions API — verify coverage/accuracy early.
- **Graph over-engineering risk** — ensure relationships are genuinely used, not decoration.
- **Eval subjectivity** — "good recommendation" is subjective; lean on objective accessibility metrics
  for hard numbers, use RAGAS for the semantic side.
- **`Category` is coarser than it looks (CONFIRMED, 2026-08-06)** — not theoretical, observed
  end-to-end: "tribal brew daily" (primarily a coffee/breakfast spot) matched all 5 non-brewery
  category searches in the original sweep, including "dessert shops," and surfaces as a dessert
  suggestion despite not being one. Google's Text Search relevance is loose enough that a place
  showing up under a category search isn't the same as the place actually specializing in it. This
  is precisely the gap `Specialty`/`FAMOUS_FOR` (§7, still pending) exists to close.

---

## 10. Tech stack

Python · FastAPI + Pydantic · AlloyDB/PostgreSQL + pgvector (not built yet, §7) · Neo4j Aura
(loaded and live) · LangGraph (not yet used — current query pipeline is a plain two-stage
function call, no agent framework needed for it yet, §13) · **OpenAI (`gpt-4o-mini`) — changed
2026-08-06 from the originally planned Vertex AI/Gemini**, after hitting an Anthropic API billing
wall (Claude.ai subscription billing is separate from API billing, which needs its own funded
balance) and having existing OpenAI credits available. Embedding model choice (needed for
`SIMILAR_TO`) not yet decided — `text-embedding-3-small` is the natural default given the OpenAI
switch. GCP (Cloud Run — not yet deployed there) · Google Places API · Google Directions/Routes API
(not yet integrated) · RAGAS (not yet integrated, §7) · **React + Vite + TypeScript** frontend
(`frontend/`, replaces the earlier vague "simple functional web UI") · **Docker** (backend only,
for Railway — Vercel needs no Docker, native Vite support) · **Railway** (backend hosting, planned)
· **Vercel** (frontend hosting, planned).

---

## 11. Data freshness & idempotent ingestion

The dataset is a **snapshot** — over time it drifts from reality (places close, new ones open,
ratings/prices/hours change). Keeping it current is the *data freshness* problem.

**Design decision (do this now):** build the ingestion pipeline to be **idempotent** — re-running
it should **upsert by `place_id`** (update places that already exist, add new ones) rather than
blindly inserting. Use `place_id` as the unique key.

Why decide this now: if the pipeline blindly inserts, running it twice creates duplicate places and
a messy dataset that's painful to untangle. Designing for upsert from the start avoids that, for
almost no extra effort. "What happens if this runs twice?" is a good question to ask of any data
pipeline — idempotency is the general principle worth internalizing here.

**For v1:** build the pipeline refresh-ready, but **run it manually.** No automated scheduling needed —
a one-time (or occasionally hand-re-run) dataset is completely valid for building and running the system.

**Stretch goal (optional, additive):** automate the refresh on a schedule (a cron job). **Monthly** is
a sensible cadence for restaurant data — it doesn't change fast, and each run consumes API quota, so
more frequent isn't worth it. The pipeline runs identically whether triggered by hand or on a timer;
scheduling is just the trigger.

---

## 12. Retrieval pattern note

The core retrieval move is **filter-then-rank**: apply the structured filters (area, price, dietary)
FIRST to narrow the candidate set, THEN vector-rank the survivors by semantic similarity to the query.
Filtering before ranking keeps retrieval both precise (no irrelevant places) and efficient (smaller
set to rank). This is the same principle behind metadata-filtered retrieval generally.

---

## 13. Query pipeline (NL → Cypher → context) — built, graph-only (2026-08-06)

This is the current, working implementation of the `[Parse]` + `[Graph retrieval]` steps from §6.2 —
built ahead of the pgvector/fusion half, so it's graph-only for now, not the fused GraphRAG target.

**Two-stage design, not one-shot NL→Cypher:**
1. **Intent parsing** (`query_intent.py`) — LLM extracts a structured `QueryIntent` (category, area,
   reference_place_name, tier, a `relationship` enum — `near_each_other` / `near_reference_place` /
   `expand_to_adjacent_areas` / `none` — sort_by, limit) from the question, via OpenAI structured
   outputs (Pydantic model, not freeform text parsing).
2. **Cypher generation** (`intent_to_cypher()`) — **pure Python templating, no LLM.** Each
   `relationship` value maps to a fixed Cypher template. This is a deliberate safety property: most
   query shapes never have Cypher freely generated by an LLM against the live DB at all.

**Why two stages instead of one:** testable in isolation (intent-parsing accuracy can be measured
against a golden set independent of whether the Cypher-building logic is right — see below), and
safer (structured intent can't smuggle in a write operation the way freeform generated Cypher could).

**Schema fed to the LLM live, not hand-maintained** (`graph_schema.py`) — queries Neo4j directly for
labels, relationship types, sampled properties per label/rel-type, and the actual current `Category`
and `Area` values, and formats that into the intent-parsing system prompt. Chosen specifically so the
prompt can't drift out of sync as the graph gains new categories/areas — no hand-edited schema string
to remember to update.

**Named-place resolution (Problem A vs Problem B, both real, only one solved so far):**
- *Problem A — user names a real place imprecisely* (typo, near-miss): solved via the
  `place_name_fulltext` Lucene index (§8.1), fuzzy `~1` edit-distance query, built in
  `build_fulltext_query()`. Confirmed working: "toit" (typo-free but partial) correctly resolved to
  "Toit" with a real relevance score returned as `reference_match_confidence`.
- *Problem B — user describes a place without naming it* ("that beer place on 100 Feet Road"): NOT
  solved. No amount of better string matching fixes this — it needs semantic/embedding search over
  place name + review text, i.e. the still-pending `SIMILAR_TO`/embeddings work (§7). Flagged, not
  built.
- **No confidence/disambiguation layer yet** — a weak fuzzy match and a genuinely-not-in-the-database
  place both currently look the same to the caller (best-effort top-1 result). A real fix needs an
  explicit low-confidence path (report uncertainty / ask for clarification) rather than silently
  returning a possibly-wrong top match. Not built — noted as a gap, not resolved.

**Evaluation:** `golden_set.py` (~10 hand-labeled question → expected-intent-fields pairs, covering
each `relationship` type at least twice) + `eval_intent.py` (runs intent parsing against the golden
set, reports per-field and overall accuracy). Deliberately narrow — measures intent-parsing accuracy
only, not end-to-end answer quality (that's the full RAGAS harness, §7, still pending).

**Two independent safety layers on execution** (`run_cypher()` in `nl_to_cypher.py`), even though
`intent_to_cypher()` only ever builds read-shaped queries by construction: a keyword blocklist on the
generated query text, and execution via Neo4j's `execute_read()` transaction function, which the
server itself rejects a write against. Defense-in-depth, not the primary safety mechanism (that's the
deterministic templating itself).

**Known limitation carried into the FastAPI layer:** `main.py`'s `format_answer()` turns Cypher
results into a chat response via deterministic string templating (pattern-matched on which result
shape came back), not an LLM synthesis pass. Fast and can't hallucinate, but the phrasing is
mechanical — see §7 "still to build."
