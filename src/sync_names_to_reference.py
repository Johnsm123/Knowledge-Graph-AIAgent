"""
Propagate :Member.name from the main Neo4j to the reference DB, and
rewrite the leading name token in each Persona.description so the
visualization reflects the canonical American-English names.

Usage:
    python -m src.sync_names_to_reference
"""
import logging
from src.neo4j_connection import get_knowledge_graph, get_reference_graph

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def run():
    main = get_knowledge_graph()
    ref  = get_reference_graph()

    rows = main.run_query("MATCH (m:Member) RETURN m.member_id AS id, m.name AS name")
    m_updated = p_updated = 0
    for r in rows:
        mid, new_name = r["id"], r["name"]

        res = ref.execute_write(
            "MATCH (m:Member {member_id:$mid}) SET m.name=$name RETURN m.member_id AS id",
            {"mid": mid, "name": new_name},
        )
        if res:
            m_updated += 1

        personas = ref.run_query(
            "MATCH (p:Persona {member_id:$mid}) RETURN p.persona_id AS pid, p.description AS desc",
            {"mid": mid},
        )
        for c in personas:
            parts = (c["desc"] or "").split(", ")
            parts[0] = new_name if parts else new_name
            new_desc = ", ".join(parts) if parts else new_name
            ref.execute_write(
                "MATCH (p:Persona {persona_id:$pid}) SET p.description=$desc",
                {"pid": c["pid"], "desc": new_desc},
            )
            p_updated += 1

    logger.info(f"Reference DB: {m_updated} Member.name, {p_updated} Persona.description updated")


if __name__ == "__main__":
    run()
