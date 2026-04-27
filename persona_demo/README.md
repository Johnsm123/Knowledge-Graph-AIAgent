# Persona-Comparison Demo (isolated)

Demo-only assets for the manager. Builds a separate Neo4j Aura instance that
visualises a **persona-based** care-gap method: every real Member is paired
with an `IdealPersona` twin, and pending care gaps are derived as the
*difference* between the persona's completed set and the member's completed
set.

## What this folder does

- `seed_persona_demo_db.py` — one-shot ETL that copies every Member from the
  main DB into the demo DB, builds an `IdealPersona` twin per member, and
  wires `COMPARED_TO`, `HAS_COMPLETED`, `HAS_PENDING`, `EXCLUDED_FROM`,
  `WOULD_HAVE_COMPLETED` relationships. Idempotent — re-running clears the
  demo DB and rebuilds from current main DB state.
- `persona_demo_queries.cypher` — 10 Cypher queries to paste into Neo4j
  Browser to demonstrate the persona method.
- `.env.persona-demo.example` — template; copy to `.env.persona-demo` and
  fill in your real demo-DB credentials.

## What this folder does NOT do

- Touch the main Neo4j DB (read-only access only)
- Touch the live persona/reference DB used by the portal
- Run inside the application — nothing here is imported by `wsgi.py`,
  `care_gap_api.py`, the mobile app, or any scheduler
- Get deployed to Azure — wholly local / on-demand

## How to run

```bash
# 1. Rotate the demo-DB password in Neo4j Aura (the original was leaked).
# 2. Copy the template and fill in real values:
cp persona_demo/.env.persona-demo.example persona_demo/.env.persona-demo
# 3. Edit persona_demo/.env.persona-demo with the rotated password.

# 4. Run the seeder from the project root (uses the existing main-DB connection):
python persona_demo/seed_persona_demo_db.py
```

The seeder reads members + claims + open/closed gaps from the main DB,
re-runs the deterministic rules engine for each member to classify every
HEDIS measure as `applicable / completed / pending / excluded`, then writes
the result into the demo DB as `Member`, `IdealPersona`, and `Screening`
nodes connected by the relationships listed above.

## How to demo

1. Open Neo4j Browser pointed at the demo Aura instance.
2. Paste any query from `persona_demo_queries.cypher`. The headline ones:
   - Query #1 — single member side-by-side with their persona twin
   - Query #2 — "pending = persona's completed minus member's completed",
     the *persona-comparison* derivation in pure Cypher
   - Query #4 — top measures with most pending across the whole population
3. Show the manager the visual: Member node, COMPARED_TO edge, IdealPersona
   node, and the screenings only attached to the persona — those are the
   pending gaps. The same answer the production rules engine produces, just
   visualised through the persona lens.
