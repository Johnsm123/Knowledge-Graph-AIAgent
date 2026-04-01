"""
REST API endpoints for Care Gap workflows.
Run: python -m src.care_gap_api
"""
from flask import Flask, jsonify, request
from flask_cors import CORS
from src.care_gap_data_loader import load_all
from src.care_gap_agents import CareGapAgentSystem
from src.care_gap_neo4j import (
    get_member_open_gaps, get_member_profile, get_measure_comprehensive,
    get_member_claims_cpt_codes, check_member_exclusions
)
from src.neo4j_connection import get_knowledge_graph
import logging

app = Flask(__name__)
CORS(app)  # Enable CORS for React frontend
agent_system = None
logger = logging.getLogger(__name__)


def get_agents():
    global agent_system
    if agent_system is None:
        agent_system = CareGapAgentSystem()
    return agent_system


@app.route("/api/v1/care-gaps/load-data", methods=["POST"])
def load_data():
    """Load/reload Excel data into Neo4j. Safe to call multiple times (MERGE)."""
    try:
        load_all()
        return jsonify({"status": "success", "message": "Data loaded into Neo4j"})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/v1/care-gaps/validate/<member_id>", methods=["POST"])
def validate_member(member_id):
    """
    Run full care gap validation for a member.
    - Checks QualityMeasures golden reference
    - Validates claims against lookback window + CPT codes
    - Auto-creates CareGap nodes for detected gaps
    - Returns agent suggestions for outreach
    """
    try:
        result = get_agents().validate_and_suggest(member_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/v1/care-gaps/<member_id>", methods=["GET"])
def get_open_gaps(member_id):
    """Get all open care gaps for a member with resolution guides from golden reference."""
    try:
        gaps = get_member_open_gaps(member_id)
        profile = get_member_profile(member_id)
        return jsonify({"member_id": member_id, "profile": profile, "open_gaps": gaps})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/v1/members", methods=["GET"])
def get_all_members():
    """Get all members with their care gap status."""
    try:
        kg = get_knowledge_graph()
        members = kg.run_query("""
            MATCH (m:Member)
            OPTIONAL MATCH (m)-[:HAS_CARE_GAP]->(g:CareGap)
            WITH m, 
                 count(CASE WHEN g.is_open = true THEN 1 END) as open_gaps,
                 count(CASE WHEN g.is_open = false THEN 1 END) as closed_gaps
            OPTIONAL MATCH (m)-[:ASSIGNED_TO]->(p:Provider)
            RETURN m.member_id as member_id,
                   m.name as name,
                   m.age_str as age,
                   m.gender as gender,
                   m.dob as dob,
                   open_gaps,
                   closed_gaps,
                   p.name as pcp_name,
                   p.provider_id as pcp_id
            ORDER BY open_gaps DESC, m.name
        """, {})
        return jsonify({"members": members, "total": len(members)})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/v1/members/<member_id>/details", methods=["GET"])
def get_member_details(member_id):
    """Get comprehensive member details including profile, gaps, claims, and outreach."""
    try:
        kg = get_knowledge_graph()
        
        # Get member profile
        profile = get_member_profile(member_id)
        
        # Get care gaps
        gaps = get_member_open_gaps(member_id)
        
        # Get all claims
        claims = get_member_claims_cpt_codes(member_id)
        
        # Get outreach history
        outreach = kg.run_query("""
            MATCH (o:Outreach)-[:CONTACTS]->(m:Member {member_id: $member_id})
            OPTIONAL MATCH (o)-[:TARGETS]->(g:CareGap)-[:RELATES_TO]->(q:QualityMeasure)
            RETURN o.outreach_id as outreach_id,
                   o.channel as channel,
                   o.date as date,
                   o.status as status,
                   o.care_manager_id as care_manager_id,
                   g.care_gap_id as care_gap_id,
                   q.measure_id as measure_id,
                   q.name as measure_name
            ORDER BY o.date DESC
        """, {"member_id": member_id})
        
        # Get closed gaps
        closed_gaps = kg.run_query("""
            MATCH (m:Member {member_id: $member_id})-[:HAS_CARE_GAP]->(g:CareGap)-[:RELATES_TO]->(q:QualityMeasure)
            WHERE g.is_open = false
            RETURN g.care_gap_id as care_gap_id,
                   g.closed_on as closed_on,
                   q.measure_id as measure_id,
                   q.name as measure_name
            ORDER BY g.closed_on DESC
        """, {"member_id": member_id})
        
        return jsonify({
            "member_id": member_id,
            "profile": profile,
            "open_gaps": gaps,
            "closed_gaps": closed_gaps,
            "claims": claims,
            "outreach_history": outreach
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/v1/dashboard/stats", methods=["GET"])
def get_dashboard_stats():
    """Get dashboard statistics."""
    try:
        kg = get_knowledge_graph()
        
        # Total members
        total_members = kg.run_query("MATCH (m:Member) RETURN count(m) as count", {})[0]["count"]
        
        # Members with open gaps
        members_with_gaps = kg.run_query("""
            MATCH (m:Member)-[:HAS_CARE_GAP]->(g:CareGap)
            WHERE g.is_open = true
            RETURN count(DISTINCT m) as count
        """, {})[0]["count"]
        
        # Members without gaps (compliant)
        compliant_members = total_members - members_with_gaps
        
        # Total open gaps
        total_open_gaps = kg.run_query("""
            MATCH (g:CareGap)
            WHERE g.is_open = true
            RETURN count(g) as count
        """, {})[0]["count"]
        
        # Gaps by measure
        gaps_by_measure = kg.run_query("""
            MATCH (g:CareGap)-[:RELATES_TO]->(q:QualityMeasure)
            WHERE g.is_open = true
            RETURN q.measure_id as measure_id,
                   q.name as measure_name,
                   count(g) as gap_count
            ORDER BY gap_count DESC
        """, {})
        
        # Recent outreach
        recent_outreach = kg.run_query("""
            MATCH (o:Outreach)
            RETURN count(o) as total_outreach,
                   count(CASE WHEN o.status = 'Completed' THEN 1 END) as completed,
                   count(CASE WHEN o.status = 'Scheduled' THEN 1 END) as scheduled
        """, {})[0]
        
        return jsonify({
            "total_members": total_members,
            "members_with_gaps": members_with_gaps,
            "compliant_members": compliant_members,
            "total_open_gaps": total_open_gaps,
            "gaps_by_measure": gaps_by_measure,
            "outreach_stats": recent_outreach
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/v1/chat/send", methods=["POST"])
def send_chat_message():
    """Send chat message to member (simulated for now)."""
    try:
        data = request.json
        member_id = data.get("member_id")
        message = data.get("message")
        sender = data.get("sender", "care_manager")
        
        # In production, this would integrate with SMS/Email service
        # For now, we'll just log and return success
        logger.info(f"Chat message to {member_id}: {message}")
        
        return jsonify({
            "status": "success",
            "message": "Message sent successfully",
            "timestamp": "2025-01-15T10:30:00Z"
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/v1/appointments/book", methods=["POST"])
def book_appointment():
    """Book appointment for member."""
    try:
        data = request.json
        member_id = data.get("member_id")
        measure_id = data.get("measure_id")
        appointment_date = data.get("appointment_date")
        provider_id = data.get("provider_id")
        
        # In production, this would integrate with scheduling system
        logger.info(f"Booking appointment for {member_id}: {measure_id} on {appointment_date}")
        
        return jsonify({
            "status": "success",
            "appointment_id": f"APT-{member_id}-{measure_id}",
            "message": "Appointment booked successfully"
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/v1/measures/<measure_id>", methods=["GET"])
def get_measure_details(measure_id):
    """Get comprehensive measure details from golden reference."""
    try:
        measure = get_measure_comprehensive(measure_id)
        if not measure:
            return jsonify({"status": "error", "error": "Measure not found"}), 404
        return jsonify(measure)
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/v1/members/add", methods=["POST"])
def add_member():
    """Add new member with complete details to Neo4j."""
    try:
        from src.care_gap_neo4j import merge_member, merge_enrollment
        data = request.json
        
        # Validate required fields
        required = ["member_id", "name", "dob", "gender", "pcp_id", "plan_id"]
        for field in required:
            if not data.get(field):
                return jsonify({"status": "error", "error": f"Missing required field: {field}"}), 400
        
        # Create member node
        merge_member(
            member_id=data["member_id"],
            name=data["name"],
            dob=data["dob"],
            gender=data["gender"],
            pcp_id=data["pcp_id"],
            zip_code=data.get("zip_code", ""),
            enrollment_start=data.get("enrollment_start", data["dob"]),
            enrollment_end=data.get("enrollment_end", "2025-12-31"),
            age_str=data.get("age_str", "")
        )
        
        # Create enrollment relationships
        merge_enrollment(
            member_id=data["member_id"],
            plan_id=data["plan_id"],
            pcp_id=data["pcp_id"],
            effective_from=data.get("enrollment_start", data["dob"]),
            effective_to=data.get("enrollment_end", "2025-12-31")
        )
        
        return jsonify({
            "status": "success",
            "message": f"Member {data['member_id']} added successfully",
            "member_id": data["member_id"]
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/v1/providers/list", methods=["GET"])
def get_providers():
    """Get all providers for dropdown selection."""
    try:
        kg = get_knowledge_graph()
        providers = kg.run_query("""
            MATCH (p:Provider)
            RETURN p.provider_id as provider_id,
                   p.name as name,
                   p.specialty as specialty,
                   p.network_status as network_status
            ORDER BY p.name
        """, {})
        return jsonify({"providers": providers})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/v1/members/<member_id>/compare", methods=["GET"])
def compare_member(member_id):
    """Compare member with similar members and provide improvement recommendations."""
    try:
        kg = get_knowledge_graph()
        
        # Get current member details
        current_member = kg.run_query("""
            MATCH (m:Member {member_id: $member_id})
            OPTIONAL MATCH (m)-[:HAS_CARE_GAP]->(g:CareGap)
            WITH m, 
                 count(CASE WHEN g.is_open = true THEN 1 END) as open_gaps,
                 count(CASE WHEN g.is_open = false THEN 1 END) as closed_gaps
            RETURN m.member_id as member_id,
                   m.name as name,
                   m.age_str as age,
                   m.gender as gender,
                   m.dob as dob,
                   open_gaps,
                   closed_gaps
        """, {"member_id": member_id})
        
        if not current_member:
            return jsonify({"status": "error", "error": "Member not found"}), 404
        
        current = current_member[0]
        
        # Parse age from "35 Years, 5 Months" format
        age_str = current["age"]
        try:
            age = int(age_str.split()[0]) if age_str else 0
        except (ValueError, AttributeError, IndexError):
            age = 0
        
        # Find similar members (same gender, similar age range ±5 years)
        similar_members = kg.run_query("""
            MATCH (m:Member)
            WHERE m.member_id <> $member_id
              AND m.gender = $gender
            OPTIONAL MATCH (m)-[:HAS_CARE_GAP]->(g:CareGap)
            WITH m,
                 count(CASE WHEN g.is_open = true THEN 1 END) as open_gaps,
                 count(CASE WHEN g.is_open = false THEN 1 END) as closed_gaps,
                 count(g) as total_gaps
            OPTIONAL MATCH (m)-[:HAS_CLAIM]->(c:Claim)
            WITH m, open_gaps, closed_gaps, total_gaps, count(c) as total_claims
            RETURN m.member_id as member_id,
                   m.name as name,
                   m.age_str as age,
                   m.gender as gender,
                   open_gaps,
                   closed_gaps,
                   total_gaps,
                   total_claims
            ORDER BY open_gaps ASC, closed_gaps DESC
            LIMIT 10
        """, {
            "member_id": member_id,
            "gender": current["gender"]
        })
        
        # Filter similar members by age range in Python
        filtered_similar = []
        for member in similar_members:
            try:
                member_age = int(member["age"].split()[0]) if member["age"] else 0
                if abs(member_age - age) <= 5:
                    filtered_similar.append(member)
            except (ValueError, AttributeError, IndexError):
                continue
        
        # Get current member's open gaps with details
        current_gaps = kg.run_query("""
            MATCH (m:Member {member_id: $member_id})-[:HAS_CARE_GAP]->(g:CareGap)-[:RELATES_TO]->(q:QualityMeasure)
            WHERE g.is_open = true
            RETURN g.care_gap_id as care_gap_id,
                   q.measure_id as measure_id,
                   q.name as measure_name,
                   q.description as description,
                   q.lookback_months as lookback_months,
                   g.created_on as created_on
        """, {"member_id": member_id})
        
        # Get CPT codes from CodeSet nodes
        for gap in current_gaps:
            cpt_codes = kg.run_query("""
                MATCH (q:QualityMeasure {measure_id: $measure_id})-[:REQUIRES_CODES]->(cs:CodeSet)
                WHERE cs.code_type = 'CPT'
                RETURN cs.codes as codes
            """, {"measure_id": gap["measure_id"]})
            gap["cpt_codes"] = ", ".join(cpt_codes[0]["codes"]) if cpt_codes and cpt_codes[0]["codes"] else "N/A"
        
        # Get best practices from quality measures
        improvement_guidelines = kg.run_query("""
            MATCH (m:Member {member_id: $member_id})-[:HAS_CARE_GAP]->(g:CareGap)-[:RELATES_TO]->(q:QualityMeasure)
            WHERE g.is_open = true
            OPTIONAL MATCH (q)-[:HAS_BEST_PRACTICES]->(bp:BestPractices)
            OPTIONAL MATCH (q)-[:FOLLOWS_GUIDELINE]->(cg:ClinicalGuideline)
            RETURN q.measure_id as measure_id,
                   q.name as measure_name,
                   bp.practices as best_practices,
                   cg.acceptable as acceptable_documentation,
                   q.numerator_criteria as numerator_criteria
        """, {"member_id": member_id})
        
        # Calculate comparison metrics (only consider open gaps for performance)
        better_performers = [m for m in filtered_similar if m["open_gaps"] < current["open_gaps"]]
        avg_open_gaps = sum(m["open_gaps"] for m in filtered_similar) / len(filtered_similar) if filtered_similar else 0
        avg_closed_gaps = sum(m["closed_gaps"] for m in filtered_similar) / len(filtered_similar) if filtered_similar else 0
        
        # Percentile rank: lower open gaps = better performance (higher percentile)
        # If member has 0 open gaps, they're in top percentile
        percentile = calculate_percentile(current["open_gaps"], [m["open_gaps"] for m in filtered_similar])
        
        return jsonify({
            "current_member": current,
            "similar_members": filtered_similar,
            "better_performers": better_performers,
            "current_gaps": current_gaps,
            "improvement_guidelines": improvement_guidelines,
            "comparison_metrics": {
                "current_open_gaps": current["open_gaps"],
                "current_closed_gaps": current["closed_gaps"],
                "avg_open_gaps_similar": round(avg_open_gaps, 1),
                "avg_closed_gaps_similar": round(avg_closed_gaps, 1),
                "percentile_rank": percentile,
                "total_similar_members": len(filtered_similar),
                "better_performers_count": len(better_performers)
            }
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "error": str(e)}), 500


def calculate_percentile(value, values_list):
    """Calculate percentile rank based on open gaps (lower gaps = higher percentile = better)."""
    if not values_list:
        return 100 if value == 0 else 50
    
    # Special case: if member has 0 open gaps, they're always top performer
    if value == 0:
        return 100
    
    # Count members with MORE open gaps (worse performance)
    worse_count = sum(1 for v in values_list if v > value)
    
    # Count members with SAME number of gaps
    same_count = sum(1 for v in values_list if v == value)
    
    # Percentile = (worse + 0.5*same) / total * 100
    # This gives mid-point ranking for ties
    percentile = ((worse_count + 0.5 * same_count) / len(values_list)) * 100
    
    return round(percentile)


@app.route("/api/v1/plans/list", methods=["GET"])
def get_plans():
    """Get all benefit plans for dropdown selection."""
    try:
        kg = get_knowledge_graph()
        plans = kg.run_query("""
            MATCH (b:BenefitPlan)
            RETURN b.plan_id as plan_id,
                   b.copay as copay,
                   b.deductible as deductible,
                   b.preventive_covered as preventive_covered
            ORDER BY b.plan_id
        """, {})
        return jsonify({"plans": plans})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5001, use_reloader=False)
