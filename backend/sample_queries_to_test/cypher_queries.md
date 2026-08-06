# Sample Cypher queries

Ready-to-paste queries for the Neo4j Aura instance (Neo4j Browser / Query tab).
Schema reference: `blr-food-recommender-context.md` §8.1.

Rule of thumb for the graph view vs. table view in Neo4j Browser: `RETURN`ing
whole nodes/relationships (e.g. `p1`, `r`, `p2`) renders as a graph;
`RETURN`ing extracted properties (e.g. `p1.name`) renders as a table.

---

## 1. Bars in Indiranagar that are near each other (table)

```cypher
MATCH (p1:Place)-[:LOCATED_IN]->(:Area {name: "Indiranagar"}),
      (p1)-[:IN_CATEGORY]->(:Category {name: "bars"}),
      (p1)-[r:ADJACENT_TO]-(p2:Place),
      (p2)-[:LOCATED_IN]->(:Area {name: "Indiranagar"}),
      (p2)-[:IN_CATEGORY]->(:Category {name: "bars"})
RETURN p1.name AS bar_a, p2.name AS bar_b, r.distance_km
ORDER BY r.distance_km
```

## 2. Same thing, as a graph

```cypher
MATCH (p1:Place)-[:LOCATED_IN]->(:Area {name: "Indiranagar"}),
      (p1)-[:IN_CATEGORY]->(:Category {name: "bars"}),
      (p1)-[r:ADJACENT_TO]-(p2:Place)-[:IN_CATEGORY]->(:Category {name: "bars"})
RETURN p1, r, p2
```

## 3. A 3-stop cafe-hopping route

Chains `ADJACENT_TO` two hops instead of one -- a flat SQL filter can't do
this in a single query, this is the graph earning its keep.

```cypher
MATCH (a:Place)-[:ADJACENT_TO]-(b:Place)-[:ADJACENT_TO]-(c:Place)
WHERE a.id <> c.id
  AND (a)-[:LOCATED_IN]->(:Area {name: "Indiranagar"})
RETURN a.name, b.name, c.name
LIMIT 10
```

## 4. Search-expansion fallback via adjacent areas

Not enough bars in Indiranagar itself? Pull from `NEAR` areas too -- this is
what `Area -[NEAR]-> Area` exists for.

```cypher
MATCH (origin:Area {name: "Indiranagar"})
OPTIONAL MATCH (origin)-[:NEAR]-(nearby:Area)
WITH origin, collect(nearby) + origin AS areas
UNWIND areas AS area
MATCH (p:Place)-[:LOCATED_IN]->(area), (p)-[:IN_CATEGORY]->(:Category {name: "bars"})
RETURN DISTINCT p.name, area.name
ORDER BY area.name
```

## 5. Top-rated bar in Indiranagar + what's walkable from it

Combines a structured filter (rating) with a graph traversal (`ADJACENT_TO`)
in one query -- the filter-then-rank-then-traverse pattern the whole project
is built around.

```cypher
MATCH (best:Place)-[:LOCATED_IN]->(:Area {name: "Indiranagar"}),
      (best)-[:IN_CATEGORY]->(:Category {name: "bars"})
WITH best ORDER BY best.rating DESC LIMIT 1
MATCH (best)-[r:ADJACENT_TO]-(other:Place)
RETURN best.name AS top_bar, best.rating, other.name AS walkable_from_it, r.distance_km
ORDER BY r.distance_km
```

---

## Other useful ad hoc checks

Whole graph (small dataset only -- gets cluttered fast, see the conversation
about this):
```cypher
MATCH (n) RETURN n
```

One category, decluttered:
```cypher
MATCH (c:Category {name: "breweries"})<-[:IN_CATEGORY]-(p:Place) RETURN c, p
```

Node/relationship counts (same as `load_graph.py`'s summary output):
```cypher
MATCH (n) RETURN labels(n)[0] AS label, count(*) AS count ORDER BY label
```
```cypher
MATCH ()-[r]->() RETURN type(r) AS rel_type, count(*) AS count ORDER BY rel_type
```