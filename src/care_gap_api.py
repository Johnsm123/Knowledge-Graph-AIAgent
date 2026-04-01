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


if __name__ == "__main__":
    app.run(debug=True, port=5001, use_reloader=False)
