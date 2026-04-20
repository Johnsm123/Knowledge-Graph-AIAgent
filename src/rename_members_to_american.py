"""
One-shot: rename existing Members whose name is non-American-English
(Tamil/Indian/placeholder/etc) to proper American English names.
Keeps gender/DOB/member_id intact. Idempotent — re-running only touches
names still in the rename map.

Usage:
    python -m src.rename_members_to_american
"""
import logging
from src.neo4j_connection import get_knowledge_graph

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# member_id -> new English name (gender-consistent with DB)
RENAME_MAP = {
    "M0001": "Hayden Parker",       # M
    "M0002": "Taylor Mitchell",     # M
    "M0005": "Rowan Foster",        # M
    "M0008": "Rowan Bennett",       # F
    "M0009": "Quinn Harper",        # F
    "M0011": "Quinn Sullivan",      # F
    "M0012": "Lennox Hayes",        # F
    "M0013": "Cameron Brooks",      # M
    "M0014": "Rowan Carter",        # F
    "M0015": "Hannah Morgan",       # F
    "M0018": "Emery Hamilton",      # F
    "M0021": "Finley Watson",       # F
    "M0022": "Morgan Russell",      # M
    "M0023": "Blair Coleman",       # M
    "M0024": "Peyton Harrison",     # M
    "M0025": "Riley Sanders",       # F
    "M0029": "Dakota Reynolds",     # F
    "M0034": "John Samuel Carter",  # M
    "M0035": "Nathan Cooper",       # M
    "M0036": "Jacob Hayes",         # M
    "M0037": "Joseph Bennett",      # M
    "M0038": "Rebecca Porter",      # F
    "M0039": "Rachel Morgan",       # F
    "M0040": "Tyler Jackson",       # M
    "M0042": "Brianna Collins",     # F
    "M0043": "Johnny Walker",       # M
    "M0044": "Ashley Murphy",       # F (DB stored gender=Female)
    "M0045": "Grace Hamilton",      # F
    "M0046": "Jane Adams",          # F
    "M0047": "Frank Edwards",       # M
    "M0048": "Harold Parker",       # M
    "M0049": "Emily Sharp",         # F
    "M0050": "Richard Collins",     # M
    "M0108": "Joshua Mitchell",     # M
    "M0051": "Angela Porter",       # F
    "M0052": "Victor Singleton",    # M
    "M0054": "Adam Griffin",        # M
    "M0055": "Kathleen Newman",     # F
    "M0056": "Steven Morris",       # M
    "M0058": "Derek Jordan",        # M
    "M0065": "Matthew Donovan",     # M
    "M0066": "Victoria Knight",     # F
    "M0068": "Sandra Matthews",     # F
    "M0069": "Robert Shaw",         # M
    "M0071": "Vincent Kohl",        # M
    "M0072": "Brandon Barnes",      # M
    "M0073": "Samuel Matthews",     # M
    "M0075": "Ronald Jefferson",    # M
    "M0086": "Priscilla Nelson",    # F
    "M0087": "Ray Anderson",        # M
    "M0089": "Raymond Fisher",      # M
    "M0090": "Paige Sherwood",      # F
    "M0091": "Annette Douglas",     # F
    "M0092": "Michael Alan Keller", # M
    "M0093": "Laura Vincent",       # F
    "M0095": "Paige Richardson",    # F
    "M0096": "Anna Mitchell",       # F
    "M0097": "Marcus Holloway",     # M
    "M0098": "Martha Kendrick",     # F
    "M0100": "Stephanie Ross",      # F
    "M0101": "Vincent Harper",      # M
    "M0103": "Preston Manning",     # M
    "M0104": "Ralph Kendall",       # M
    "M0105": "Rhonda Taylor",       # F
    "M0106": "Ruth Stanton",        # F
    "M0107": "Russell Peterson",    # M
    "M0109": "Renee Sullivan",      # F
    "M0110": "Priscilla Keaton",    # F
    "M0111": "Howard Sterling",     # M
    "M0112": "Laura Dawson",        # F
    "M0113": "Stuart Vincent",      # M
    "M0114": "Marlene Kingston",    # F
    "M0115": "Arthur Redford",      # M
    "M0116": "Diana Neal",          # F
    "M0117": "Ronald Ivers",        # M
    "M0118": "Kathleen Sumner",     # F
    "M0119": "Victor Parks",        # M
    "M0120": "Paula Ramsey",        # F
    "M0121": "Kurt Boland",         # M
    "M0125": "Aaron Radford",       # M
    "M0128": "Katherine Sumner",    # F
    "M0129": "Vincent Parks",       # M
    "M0130": "Paula Randall",       # F
    "M0132": "Jonathan Vincent",    # M
    "M0133": "Patricia Vaughn",     # F
    "M0134": "Dennis Karlsson",     # M
    "M0135": "Paige Raymond",       # F
}


def run():
    kg = get_knowledge_graph()
    updated = 0
    for member_id, new_name in RENAME_MAP.items():
        rows = kg.execute_write(
            "MATCH (m:Member {member_id:$mid}) SET m.name=$name RETURN m.member_id AS id, m.name AS name",
            {"mid": member_id, "name": new_name},
        )
        if rows:
            updated += 1
            logger.info(f"  {member_id} -> {new_name}")
        else:
            logger.warning(f"  {member_id} not found — skipped")
    logger.info(f"Renamed {updated} members.")


if __name__ == "__main__":
    run()
