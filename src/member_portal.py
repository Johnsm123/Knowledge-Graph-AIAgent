"""
Member-facing Portal — Flask Blueprint.

Serves HTML pages linked from automated outreach emails so members can:
  1. Review their care gap analysis and respond Yes / No per gap
  2. Find nearby labs/physicians via Google Places + Leaflet map
  3. Pick available appointment time slots for accepted gaps
  4. Receive a booking confirmation (also sent via email)

Security: every portal URL contains an HMAC token derived from the member_id
and a server-side secret.  No login required — the link *is* the credential.
"""

import hashlib
import hmac
import json as _json
import logging
import uuid
from datetime import datetime, timedelta

import requests as http_requests
from flask import Blueprint, request, jsonify

from src.neo4j_connection import get_knowledge_graph
from src.care_gap_neo4j import (
    get_member_open_gaps,
    get_member_profile,
    merge_appointment,
    get_appointment,
    merge_outreach,
)

portal_bp = Blueprint("member_portal", __name__)
_logger = logging.getLogger(__name__)

_PORTAL_SECRET = "hedis-care-gap-portal-2025"  # demo secret


# ── Token helpers ────────────────────────────────────────────────────────────

def _make_token(member_id: str) -> str:
    return hmac.new(
        _PORTAL_SECRET.encode(), member_id.encode(), hashlib.sha256
    ).hexdigest()[:24]


def _verify_token(member_id: str, token: str) -> bool:
    return hmac.compare_digest(_make_token(member_id), token)


def get_portal_url(member_id: str) -> str:
    """Return the base portal URL for a member (used when composing emails)."""
    token = _make_token(member_id)
    return f"http://localhost:5001/portal/{member_id}/{token}"


# ── Available time-slot generator ────────────────────────────────────────────

def _generate_slots(days_ahead: int = 7):
    """Generate 30-min appointment slots for the next *days_ahead* business days."""
    slots = []
    day = datetime.now() + timedelta(days=1)
    biz_days = 0
    while biz_days < days_ahead:
        if day.weekday() < 5:  # Mon-Fri
            for hour in range(8, 17):
                for minute in (0, 30):
                    if hour == 16 and minute == 30:
                        continue
                    slots.append({
                        "date": day.strftime("%Y-%m-%d"),
                        "time": f"{hour:02d}:{minute:02d}",
                        "display_date": day.strftime("%A, %B %d, %Y"),
                        "display_time": f"{hour % 12 or 12}:{minute:02d} {'AM' if hour < 12 else 'PM'}",
                    })
            biz_days += 1
        day += timedelta(days=1)
    return slots


def _get_booked_slots():
    """Return set of (date, time) tuples already booked across all members."""
    kg = get_knowledge_graph()
    rows = kg.run_query("""
        MATCH (a:Appointment)
        WHERE a.status <> 'Completed'
        RETURN a.appointment_date AS d, a.appointment_time AS t
    """, {})
    return {(r["d"], r["t"]) for r in rows if r["d"] and r["t"]}


# ── Google Places API proxy ─────────────────────────────────────────────────

# Map HEDIS measure IDs to Google Places search keywords
_MEASURE_PLACE_KEYWORDS = {
    "BCS": "mammography radiology breast screening",
    "CCS": "gynecology cervical screening pap smear",
    "COL": "gastroenterology colonoscopy endoscopy",
    "CBP": "cardiology blood pressure clinic",
    "GSD": "diabetes endocrinology HbA1c lab",
    "EED": "ophthalmology diabetic eye exam retinal screening",
    "KED": "nephrology kidney screening renal lab",
    "BPD": "diabetes endocrinology blood glucose lab",
    "AAP": "primary care screening lab",
    "CHL": "STD testing chlamydia screening lab",
}


@portal_bp.route("/portal/api/nearby-labs", methods=["GET"])
def nearby_labs_api():
    """Proxy for Google Places Nearby Search.

    Query params: lat, lng, radius (metres, default 5000),
                  measure_id (optional — refines search keywords).
    Returns JSON list of places with name, address, lat, lng, rating, place_id.
    """
    from config.settings import settings as cfg

    api_key = cfg.google_maps_api_key
    if not api_key:
        return jsonify({"error": "Google Maps API key not configured"}), 500

    lat = request.args.get("lat")
    lng = request.args.get("lng")
    if not lat or not lng:
        return jsonify({"error": "lat and lng are required"}), 400

    radius = request.args.get("radius", "5000")
    measure_id = request.args.get("measure_id", "")

    # Build keyword — combine measure-specific + generic medical terms
    keyword = _MEASURE_PLACE_KEYWORDS.get(measure_id, "medical lab diagnostic center")

    url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    params = {
        "location": f"{lat},{lng}",
        "radius": radius,
        "keyword": keyword,
        "type": "health",
        "key": api_key,
    }

    try:
        resp = http_requests.get(url, params=params, timeout=10)
        data = resp.json()
    except Exception as exc:
        _logger.warning(f"Google Places API error: {exc}")
        return jsonify({"error": "Places API request failed"}), 502

    results = []
    for place in data.get("results", [])[:15]:
        loc = place.get("geometry", {}).get("location", {})
        results.append({
            "place_id": place.get("place_id", ""),
            "name": place.get("name", ""),
            "address": place.get("vicinity", ""),
            "lat": loc.get("lat"),
            "lng": loc.get("lng"),
            "rating": place.get("rating"),
            "total_ratings": place.get("user_ratings_total", 0),
            "open_now": place.get("opening_hours", {}).get("open_now"),
            "types": place.get("types", []),
        })

    return jsonify({"results": results, "status": data.get("status", "UNKNOWN")})


@portal_bp.route("/portal/api/geocode", methods=["GET"])
def geocode_api():
    """Proxy for Google Geocoding API — convert address text to lat/lng."""
    from config.settings import settings as cfg

    api_key = cfg.google_maps_api_key
    if not api_key:
        return jsonify({"error": "Google Maps API key not configured"}), 500

    address = request.args.get("address", "").strip()
    if not address:
        return jsonify({"error": "address is required"}), 400

    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {"address": address, "key": api_key}

    try:
        resp = http_requests.get(url, params=params, timeout=10)
        data = resp.json()
    except Exception as exc:
        _logger.warning(f"Geocoding error: {exc}")
        return jsonify({"error": "Geocoding request failed"}), 502

    results = data.get("results", [])
    if not results:
        return jsonify({"error": "No results", "lat": None, "lng": None})

    loc = results[0].get("geometry", {}).get("location", {})
    return jsonify({
        "lat": loc.get("lat"),
        "lng": loc.get("lng"),
        "formatted_address": results[0].get("formatted_address", ""),
    })


@portal_bp.route("/portal/api/place-details", methods=["GET"])
def place_details_api():
    """Proxy for Google Places Details — returns phone, website, hours."""
    from config.settings import settings as cfg

    api_key = cfg.google_maps_api_key
    if not api_key:
        return jsonify({"error": "Google Maps API key not configured"}), 500

    place_id = request.args.get("place_id")
    if not place_id:
        return jsonify({"error": "place_id is required"}), 400

    url = "https://maps.googleapis.com/maps/api/place/details/json"
    params = {
        "place_id": place_id,
        "fields": "name,formatted_address,formatted_phone_number,website,opening_hours,geometry,rating,user_ratings_total",
        "key": api_key,
    }

    try:
        resp = http_requests.get(url, params=params, timeout=10)
        data = resp.json()
    except Exception as exc:
        _logger.warning(f"Google Place Details error: {exc}")
        return jsonify({"error": "Place Details request failed"}), 502

    r = data.get("result", {})
    loc = r.get("geometry", {}).get("location", {})
    return jsonify({
        "name": r.get("name", ""),
        "address": r.get("formatted_address", ""),
        "phone": r.get("formatted_phone_number", ""),
        "website": r.get("website", ""),
        "rating": r.get("rating"),
        "total_ratings": r.get("user_ratings_total", 0),
        "hours": r.get("opening_hours", {}).get("weekday_text", []),
        "lat": loc.get("lat"),
        "lng": loc.get("lng"),
    })


# ── 1. Gap response page — member reviews gaps and clicks Yes / No ───────────

@portal_bp.route("/portal/<member_id>/<token>", methods=["GET"])
def portal_gap_review(member_id, token):
    if not _verify_token(member_id, token):
        return "<h2>Invalid or expired link.</h2>", 403

    profile = get_member_profile(member_id)
    if not profile:
        return "<h2>Member not found.</h2>", 404

    gaps = get_member_open_gaps(member_id)
    name = profile.get("name", member_id)

    if not gaps:
        return _html_page("No Open Care Gaps", f"""
            <div class="card">
              <h2>Hi {name},</h2>
              <p>Great news — you currently have <strong>no open care gaps</strong>.
              You are compliant with all quality measures. Keep up the great work!</p>
            </div>
        """)

    gap_cards = ""
    for g in gaps:
        gap_cards += f"""
        <div class="gap-card">
          <div class="gap-title">{g['measure_name']} <span class="badge">{g['measure_id']}</span></div>
          <p class="gap-desc">{g.get('resolution_guide') or ''}</p>
          <table class="gap-codes">
            <tr><td><strong>CPT Code</strong></td><td><code>{g.get('primary_cpt_code') or 'N/A'}</code></td></tr>
            <tr><td><strong>ICD-10</strong></td><td><code>{g.get('primary_icd10') or 'N/A'}</code></td></tr>
            <tr><td><strong>Lookback</strong></td><td>{g.get('lookback_months') or '12'} months</td></tr>
          </table>
          <div class="btn-row">
            <label class="radio-btn yes-btn">
              <input type="checkbox" name="accepted" value="{g['care_gap_id']}" checked />
              <span>Yes, I want this screening</span>
            </label>
          </div>
        </div>
        """

    return _html_page(f"Care Gap Analysis — {name}", f"""
        <div class="header-banner">
          <h1>HealthCare Management Portal</h1>
          <p>Preventive Care Analysis for <strong>{name}</strong></p>
        </div>
        <div class="card">
          <h2>Your Recommended Screenings</h2>
          <p>Our care team has identified the following preventive screenings for you.
             Please review each one and uncheck any you do <em>not</em> wish to schedule.</p>
          <form method="POST" action="/portal/{member_id}/{token}/respond">
            {gap_cards}
            <button type="submit" class="primary-btn">Continue to Scheduling &rarr;</button>
          </form>
        </div>
    """)


# ── 2. Process Yes/No responses and redirect to scheduling ──────────────────

@portal_bp.route("/portal/<member_id>/<token>/respond", methods=["POST"])
def portal_gap_respond(member_id, token):
    if not _verify_token(member_id, token):
        return "<h2>Invalid or expired link.</h2>", 403

    accepted_ids = request.form.getlist("accepted")  # list of care_gap_ids

    if not accepted_ids:
        return _html_page("No Screenings Selected", f"""
            <div class="card">
              <h2>No screenings selected</h2>
              <p>You did not select any screenings. If this was a mistake,
              <a href="/portal/{member_id}/{token}">go back</a> and try again.</p>
              <p>Thank you for reviewing your care gap analysis.</p>
            </div>
        """)

    # Store accepted gap IDs in query string for the scheduling page
    gap_params = "&".join(f"gap={gid}" for gid in accepted_ids)
    return f"""<html><head><meta http-equiv="refresh" content="0;url=/portal/{member_id}/{token}/schedule?{gap_params}" /></head></html>"""


# ── 3. Scheduling page — find lab + pick time slots ────────────────────────────

@portal_bp.route("/portal/<member_id>/<token>/schedule", methods=["GET"])
def portal_schedule(member_id, token):
    if not _verify_token(member_id, token):
        return "<h2>Invalid or expired link.</h2>", 403

    profile = get_member_profile(member_id)
    name = profile.get("name", member_id) if profile else member_id
    accepted_gap_ids = request.args.getlist("gap")

    if not accepted_gap_ids:
        return _html_page("Error", "<div class='card'><p>No gaps specified.</p></div>")

    # Fetch gap details
    gaps = get_member_open_gaps(member_id)
    selected_gaps = [g for g in gaps if g["care_gap_id"] in accepted_gap_ids]

    if not selected_gaps:
        return _html_page("Error", "<div class='card'><p>No matching open gaps found.</p></div>")

    # Generate available slots and mark booked ones
    all_slots = _generate_slots(7)
    booked = _get_booked_slots()

    # Group slots by date
    from collections import OrderedDict
    slots_by_date = OrderedDict()
    for s in all_slots:
        slots_by_date.setdefault(s["date"], []).append(s)

    # Build per-gap slot HTML
    gap_sections = ""
    gaps_json_arr = []
    for g in selected_gaps:
        slot_html = ""
        for date_key, day_slots in slots_by_date.items():
            display_date = day_slots[0]["display_date"]
            slot_html += f'<div class="date-header">{display_date}</div><div class="slot-grid">'
            for s in day_slots:
                is_booked = (s["date"], s["time"]) in booked
                disabled = "disabled" if is_booked else ""
                booked_label = ' (Booked)' if is_booked else ""
                slot_html += f"""
                <label class="slot-label {'slot-disabled' if is_booked else ''}">
                  <input type="radio" name="slot_{g['care_gap_id']}" value="{s['date']}|{s['time']}" {disabled} />
                  <span>{s['display_time']}{booked_label}</span>
                </label>"""
            slot_html += "</div>"

        gap_sections += f"""
        <div class="schedule-gap" id="gap-section-{g['care_gap_id']}">
          <div class="gap-title">{g['measure_name']} <span class="badge">{g['measure_id']}</span></div>

          <!-- Lab selection area -->
          <div class="lab-selection" id="lab-sel-{g['care_gap_id']}">
            <div class="lab-selected-banner" id="lab-banner-{g['care_gap_id']}" style="display:none;">
              <strong>Selected Lab:</strong>
              <span id="lab-name-{g['care_gap_id']}"></span> —
              <span id="lab-addr-{g['care_gap_id']}"></span>
              <button type="button" class="btn-change-lab" onclick="openLabFinder('{g['care_gap_id']}', '{g['measure_id']}')">Change Lab</button>
            </div>
            <div id="lab-prompt-{g['care_gap_id']}">
              <button type="button" class="btn-find-lab" onclick="openLabFinder('{g['care_gap_id']}', '{g['measure_id']}')">
                &#128205; Find Nearby Labs &amp; Physicians
              </button>
            </div>
          </div>

          <!-- Hidden fields for selected lab data -->
          <input type="hidden" name="gap_ids" value="{g['care_gap_id']}" />
          <input type="hidden" name="measure_{g['care_gap_id']}" value="{g['measure_id']}" />
          <input type="hidden" name="measure_name_{g['care_gap_id']}" value="{g['measure_name']}" />
          <input type="hidden" name="lab_name_{g['care_gap_id']}" id="hid-lab-name-{g['care_gap_id']}" value="" />
          <input type="hidden" name="lab_address_{g['care_gap_id']}" id="hid-lab-addr-{g['care_gap_id']}" value="" />
          <input type="hidden" name="lab_place_id_{g['care_gap_id']}" id="hid-lab-pid-{g['care_gap_id']}" value="" />
          <input type="hidden" name="lab_phone_{g['care_gap_id']}" id="hid-lab-phone-{g['care_gap_id']}" value="" />
          <input type="hidden" name="lab_rating_{g['care_gap_id']}" id="hid-lab-rating-{g['care_gap_id']}" value="" />

          <p style="margin-top:14px;">Select a date and time for your appointment:</p>
          <div class="slots-container">{slot_html}</div>
        </div>
        """
        gaps_json_arr.append({
            "care_gap_id": g["care_gap_id"],
            "measure_id": g["measure_id"],
            "measure_name": g["measure_name"],
        })

    gaps_json = _json.dumps(gaps_json_arr)

    # Google Maps API key for Leaflet tile layer (tiles are free, no key needed)
    from config.settings import settings as cfg
    maps_key = cfg.google_maps_api_key

    return _html_page_with_map(f"Schedule Appointments — {name}", f"""
        <div class="header-banner">
          <h1>HealthCare Management Portal</h1>
          <p>Schedule Your Appointments — <strong>{name}</strong></p>
        </div>
        <div class="card">
          <h2>Choose Lab &amp; Preferred Time Slots</h2>
          <p>For each screening, find a nearby lab or physician, then select a time slot.
             Greyed-out slots are already booked.</p>
          <form method="POST" action="/portal/{member_id}/{token}/book" id="booking-form">
            {gap_sections}
            <button type="submit" class="primary-btn">Confirm &amp; Book Appointments</button>
          </form>
        </div>

        <!-- ── Lab Finder Modal ──────────────────────────────────────────── -->
        <div id="lab-modal" class="modal-overlay" style="display:none;">
          <div class="modal-content">
            <div class="modal-header">
              <h3>&#128205; Find Nearby Labs &amp; Physicians</h3>
              <button type="button" class="modal-close" onclick="closeLabModal()">&times;</button>
            </div>

            <div class="modal-body">
              <!-- Search bar -->
              <div class="lab-search-bar">
                <input type="text" id="lab-location-input" placeholder="Enter city, address, or zip code..." />
                <button type="button" class="btn-search-loc" onclick="searchByAddress()">Search</button>
                <button type="button" class="btn-my-loc" onclick="useMyLocation()">&#128204; My Location</button>
              </div>
              <div id="lab-status" class="lab-status">Detecting your location...</div>

              <!-- Map -->
              <div id="lab-map" style="height:350px;border-radius:10px;margin:12px 0;"></div>

              <!-- Results list -->
              <div id="lab-results" class="lab-results"></div>
            </div>
          </div>
        </div>
    """, maps_key, gaps_json)


# ── 4. Book appointments and show confirmation ──────────────────────────────

@portal_bp.route("/portal/<member_id>/<token>/book", methods=["POST"])
def portal_book(member_id, token):
    if not _verify_token(member_id, token):
        return "<h2>Invalid or expired link.</h2>", 403

    profile = get_member_profile(member_id)
    name = profile.get("name", member_id) if profile else member_id
    gap_ids = request.form.getlist("gap_ids")

    if not gap_ids:
        return _html_page("Error", "<div class='card'><p>No gaps to book.</p></div>")

    from src.care_gap_api import _get_hedis_codes

    # Fallback lab map (used when member didn't select a lab from the map)
    _FALLBACK_LAB = {
        "BCS": {"lab_number": "LAB-02", "lab_specialist": "Dr. Sarah Mitchell",
                "lab_location": "Radiology & Mammography Unit, 2nd Floor"},
        "CCS": {"lab_number": "LAB-01", "lab_specialist": "Dr. James Rodriguez",
                "lab_location": "Cytology & Gynecology Lab, 1st Floor"},
        "COL": {"lab_number": "LAB-03", "lab_specialist": "Dr. Emily Chen",
                "lab_location": "Gastroenterology & Endoscopy Suite, 3rd Floor"},
        "CBP": {"lab_number": "LAB-04", "lab_specialist": "Dr. Michael Thompson",
                "lab_location": "Cardiology Clinic, 4th Floor"},
        "GSD": {"lab_number": "LAB-05", "lab_specialist": "Dr. Lisa Patel",
                "lab_location": "Diabetes & Endocrinology Center, 2nd Floor"},
        "EED": {"lab_number": "LAB-05", "lab_specialist": "Dr. Lisa Patel",
                "lab_location": "Diabetes & Endocrinology Center, 2nd Floor"},
        "KED": {"lab_number": "LAB-05", "lab_specialist": "Dr. Lisa Patel",
                "lab_location": "Renal & Nephrology Lab, 2nd Floor"},
        "BPD": {"lab_number": "LAB-05", "lab_specialist": "Dr. Lisa Patel",
                "lab_location": "Diabetes & Endocrinology Center, 2nd Floor"},
    }
    DEFAULT_LAB = {"lab_number": "LAB-01", "lab_specialist": "On-Call Specialist",
                   "lab_location": "General Screening Lab, 1st Floor"}

    bookings_html = ""
    booked_appointments = []

    for gid in gap_ids:
        slot_val = request.form.get(f"slot_{gid}", "")
        if not slot_val or "|" not in slot_val:
            continue

        appt_date, appt_time = slot_val.split("|", 1)
        measure_id = request.form.get(f"measure_{gid}", "")
        measure_name = request.form.get(f"measure_name_{gid}", measure_id)

        # Use member-selected lab from Google Places if available, else fallback
        selected_lab_name = request.form.get(f"lab_name_{gid}", "").strip()
        selected_lab_addr = request.form.get(f"lab_address_{gid}", "").strip()
        selected_lab_phone = request.form.get(f"lab_phone_{gid}", "").strip()

        if selected_lab_name:
            lab = {
                "lab_number": request.form.get(f"lab_place_id_{gid}", "GPLACE"),
                "lab_specialist": selected_lab_name,
                "lab_location": selected_lab_addr or selected_lab_name,
            }
        else:
            lab = _FALLBACK_LAB.get(measure_id, DEFAULT_LAB)

        cpt_codes, icd_codes = _get_hedis_codes(measure_id)

        appointment_id = f"APT-{member_id}-{measure_id}-{uuid.uuid4().hex[:6].upper()}"
        merge_appointment(
            appointment_id=appointment_id,
            member_id=member_id,
            measure_id=measure_id,
            appointment_date=appt_date,
            appointment_time=appt_time,
            lab_number=lab["lab_number"],
            lab_specialist=lab["lab_specialist"],
            lab_location=lab["lab_location"],
            screening_name=measure_name,
            cpt_codes=cpt_codes,
            icd_codes=icd_codes,
            provider_id=profile.get("pcp_id", ""),
            care_gap_id=gid,
        )

        # Create outreach record for the scheduling
        outreach_id = f"OUT-SCHED-{member_id}-{measure_id}-{uuid.uuid4().hex[:6].upper()}"
        merge_outreach(
            outreach_id=outreach_id,
            care_gap_id=gid,
            member_id=member_id,
            care_manager_id="AUTO-AGENT",
            channel="Member Portal",
            date=datetime.now().strftime("%Y-%m-%d"),
            status="Scheduled",
        )

        # Format display
        try:
            dt = datetime.strptime(appt_date, "%Y-%m-%d")
            friendly_date = dt.strftime("%A, %B %d, %Y")
        except Exception:
            friendly_date = appt_date
        try:
            hh, mm = appt_time.split(":")
            h = int(hh)
            friendly_time = f"{h % 12 or 12}:{mm} {'AM' if h < 12 else 'PM'}"
        except Exception:
            friendly_time = appt_time

        bookings_html += f"""
        <div class="booking-card">
          <div class="gap-title">{measure_name} <span class="badge">{measure_id}</span></div>
          <table class="gap-codes">
            <tr><td><strong>Date</strong></td><td>{friendly_date}</td></tr>
            <tr><td><strong>Time</strong></td><td>{friendly_time}</td></tr>
            <tr><td><strong>Location</strong></td><td>{lab['lab_location']}</td></tr>
            <tr><td><strong>Specialist</strong></td><td>{lab['lab_specialist']}</td></tr>
            <tr><td><strong>CPT Code</strong></td><td><code>{cpt_codes}</code></td></tr>
            <tr><td><strong>ICD-10</strong></td><td><code>{icd_codes}</code></td></tr>
            <tr><td><strong>Appointment ID</strong></td><td><code>{appointment_id}</code></td></tr>
          </table>
        </div>
        """
        booked_appointments.append({
            "appointment_id": appointment_id,
            "measure_name": measure_name,
            "date": friendly_date,
            "time": friendly_time,
        })

    # Send confirmation email
    member_email = profile.get("email", "")
    if member_email and booked_appointments:
        _send_booking_confirmation_email(member_id, name, member_email, booked_appointments)

    # Push real-time event so any open member panel auto-refreshes.
    if booked_appointments:
        try:
            from src.care_gap_api import emit_portal_event
            emit_portal_event("appointment_booked", {
                "member_id": member_id, "source": "member_portal",
                "count": len(booked_appointments),
            })
            emit_portal_event("care_gap_updated", {
                "member_id": member_id, "source": "appointment_booked",
            })
        except Exception:
            pass

    if not bookings_html:
        return _html_page("No Slots Selected", f"""
            <div class="card">
              <h2>No time slots were selected</h2>
              <p>Please go back and select a time slot for each screening.</p>
              <a href="/portal/{member_id}/{token}" class="primary-btn">Go Back</a>
            </div>
        """)

    return _html_page(f"Appointments Confirmed — {name}", f"""
        <div class="header-banner success">
          <h1>HealthCare Management Portal</h1>
          <p>Appointments Confirmed!</p>
        </div>
        <div class="card">
          <div class="success-icon">&#10004;</div>
          <h2>Your appointments have been booked!</h2>
          <p>A confirmation email has been sent to <strong>{member_email or 'your registered email'}</strong>.</p>
          {bookings_html}
        </div>
    """)


# ── Confirmation email sender ────────────────────────────────────────────────

def _send_booking_confirmation_email(member_id, name, email, appointments):
    """Send booking confirmation email via Azure Communication Services."""
    try:
        from azure.communication.email import EmailClient
        from config.settings import settings as cfg
        from src.care_gap_neo4j import merge_email

        if not cfg.azure_communication_connection_string:
            return

        rows = ""
        for a in appointments:
            rows += f"""
            <tr>
              <td style="padding:10px 16px;">{a['measure_name']}</td>
              <td style="padding:10px 16px;">{a['date']}</td>
              <td style="padding:10px 16px;">{a['time']}</td>
              <td style="padding:10px 16px;font-family:monospace;">{a['appointment_id']}</td>
            </tr>"""

        html = f"""
<html><body style="font-family:Arial,sans-serif;color:#1a1a2e;max-width:680px;margin:auto;">
<div style="background:#059669;padding:20px 32px;border-radius:8px 8px 0 0;">
  <h1 style="color:white;margin:0;font-size:22px;">HealthCare Management Portal</h1>
  <p style="color:#b3f5d9;margin:4px 0 0;">Appointment Booking Confirmation</p>
</div>
<div style="border:1px solid #dce3f5;border-top:none;padding:32px;border-radius:0 0 8px 8px;">
  <p style="font-size:16px;">Dear <strong>{name}</strong>,</p>
  <p>Your screening appointments have been successfully booked. Please review the details below.</p>
  <table style="width:100%;border-collapse:collapse;margin:24px 0;">
    <tr style="background:#059669;color:white;">
      <th style="padding:12px 16px;text-align:left;">Screening</th>
      <th style="padding:12px 16px;text-align:left;">Date</th>
      <th style="padding:12px 16px;text-align:left;">Time</th>
      <th style="padding:12px 16px;text-align:left;">Appointment ID</th>
    </tr>
    {rows}
  </table>
  <p style="color:#888;font-size:12px;">This is an automated message from the HealthCare Management Portal.</p>
</div>
</body></html>"""

        client = EmailClient.from_connection_string(cfg.azure_communication_connection_string)
        message = {
            "senderAddress": cfg.azure_communication_sender,
            "recipients": {"to": [{"address": email}]},
            "content": {
                "subject": f"Appointment Confirmation — {len(appointments)} Screening(s) Booked",
                "html": html,
            },
        }
        poller = client.begin_send(message)
        poller.result()

        # Persist email in Neo4j
        email_id = f"PORTAL-CONFIRM-{member_id}-{uuid.uuid4().hex[:8]}"
        merge_email(
            email_id=email_id,
            member_id=member_id,
            subject=f"Appointment Confirmation — {len(appointments)} Screening(s) Booked",
            body=f"Booking confirmation for {len(appointments)} appointment(s)",
            from_email=cfg.azure_communication_sender,
            to_email=email,
            timestamp=datetime.now().isoformat(),
            direction="sent",
            is_read=True,
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Confirmation email failed: {e}")


# ── HTML template helper ─────────────────────────────────────────────────────

def _html_page(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>{title}</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:'Segoe UI',Arial,sans-serif; background:#f0f4f8; color:#1a1a2e; line-height:1.6; }}
  .header-banner {{ background:#0033A1; color:white; padding:32px; text-align:center; }}
  .header-banner.success {{ background:#059669; }}
  .header-banner h1 {{ font-size:24px; margin-bottom:4px; }}
  .header-banner p {{ color:#b3c7f7; font-size:15px; }}
  .header-banner.success p {{ color:#b3f5d9; }}
  .card {{ max-width:780px; margin:32px auto; background:white; border-radius:12px; padding:32px; box-shadow:0 2px 12px rgba(0,0,0,0.08); }}
  h2 {{ font-size:20px; margin-bottom:16px; color:#0033A1; }}
  .gap-card, .schedule-gap, .booking-card {{ border:1px solid #e2e8f0; border-radius:10px; padding:20px; margin:16px 0; }}
  .gap-title {{ font-size:17px; font-weight:600; color:#1a1a2e; display:flex; align-items:center; gap:10px; }}
  .badge {{ background:#0033A1; color:white; font-size:11px; padding:3px 10px; border-radius:20px; font-weight:600; }}
  .gap-desc {{ color:#64748b; font-size:14px; margin:8px 0; }}
  .gap-location {{ color:#64748b; font-size:13px; margin:4px 0 12px; }}
  .gap-codes {{ margin:12px 0; font-size:14px; border-collapse:collapse; }}
  .gap-codes td {{ padding:4px 16px 4px 0; }}
  code {{ background:#f1f5f9; padding:2px 8px; border-radius:4px; font-size:13px; }}
  .btn-row {{ margin-top:12px; }}
  .radio-btn {{ display:inline-flex; align-items:center; gap:8px; cursor:pointer; padding:8px 16px; border:2px solid #059669; border-radius:8px; color:#059669; font-weight:600; font-size:14px; }}
  .radio-btn input {{ accent-color:#059669; width:18px; height:18px; }}
  .primary-btn {{ display:inline-block; background:#0033A1; color:white; border:none; padding:14px 32px; border-radius:8px; font-size:16px; font-weight:600; cursor:pointer; margin-top:20px; text-decoration:none; }}
  .primary-btn:hover {{ background:#002880; }}
  .success-icon {{ font-size:48px; color:#059669; text-align:center; margin:16px 0; }}
  .info-box {{ background:#f0f4ff; border-left:4px solid #0033A1; padding:16px; border-radius:4px; margin:20px 0; }}
  .info-box ul {{ padding-left:20px; margin-top:8px; }}
  .info-box li {{ margin:4px 0; font-size:14px; }}
  .date-header {{ font-weight:600; color:#0033A1; margin:16px 0 8px; font-size:15px; border-bottom:1px solid #e2e8f0; padding-bottom:6px; }}
  .slot-grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(140px,1fr)); gap:8px; margin-bottom:12px; }}
  .slot-label {{ display:flex; align-items:center; gap:6px; padding:8px 12px; border:1px solid #e2e8f0; border-radius:6px; cursor:pointer; font-size:13px; transition:all .15s; }}
  .slot-label:hover {{ border-color:#0033A1; background:#f0f4ff; }}
  .slot-label input:checked + span {{ color:#0033A1; font-weight:600; }}
  .slot-disabled {{ opacity:0.4; cursor:not-allowed; background:#f8f8f8; text-decoration:line-through; }}
  .slot-disabled input {{ pointer-events:none; }}
  .slots-container {{ max-height:400px; overflow-y:auto; border:1px solid #e2e8f0; border-radius:8px; padding:12px; margin:12px 0; }}
  .booking-card {{ background:#f0fdf4; border-color:#059669; }}
</style>
</head>
<body>
{body}
</body>
</html>"""


def _html_page_with_map(title: str, body: str, maps_key: str, gaps_json: str) -> str:
    """Extended HTML page template that includes Leaflet.js map + lab finder JavaScript."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>{title}</title>
<!-- Leaflet CSS -->
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:'Segoe UI',Arial,sans-serif; background:#f0f4f8; color:#1a1a2e; line-height:1.6; }}
  .header-banner {{ background:#0033A1; color:white; padding:32px; text-align:center; }}
  .header-banner.success {{ background:#059669; }}
  .header-banner h1 {{ font-size:24px; margin-bottom:4px; }}
  .header-banner p {{ color:#b3c7f7; font-size:15px; }}
  .header-banner.success p {{ color:#b3f5d9; }}
  .card {{ max-width:780px; margin:32px auto; background:white; border-radius:12px; padding:32px; box-shadow:0 2px 12px rgba(0,0,0,0.08); }}
  h2 {{ font-size:20px; margin-bottom:16px; color:#0033A1; }}
  .gap-card, .schedule-gap, .booking-card {{ border:1px solid #e2e8f0; border-radius:10px; padding:20px; margin:16px 0; }}
  .gap-title {{ font-size:17px; font-weight:600; color:#1a1a2e; display:flex; align-items:center; gap:10px; flex-wrap:wrap; }}
  .badge {{ background:#0033A1; color:white; font-size:11px; padding:3px 10px; border-radius:20px; font-weight:600; }}
  .primary-btn {{ display:inline-block; background:#0033A1; color:white; border:none; padding:14px 32px; border-radius:8px; font-size:16px; font-weight:600; cursor:pointer; margin-top:20px; text-decoration:none; }}
  .primary-btn:hover {{ background:#002880; }}
  .date-header {{ font-weight:600; color:#0033A1; margin:16px 0 8px; font-size:15px; border-bottom:1px solid #e2e8f0; padding-bottom:6px; }}
  .slot-grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(140px,1fr)); gap:8px; margin-bottom:12px; }}
  .slot-label {{ display:flex; align-items:center; gap:6px; padding:8px 12px; border:1px solid #e2e8f0; border-radius:6px; cursor:pointer; font-size:13px; transition:all .15s; }}
  .slot-label:hover {{ border-color:#0033A1; background:#f0f4ff; }}
  .slot-label input:checked + span {{ color:#0033A1; font-weight:600; }}
  .slot-disabled {{ opacity:0.4; cursor:not-allowed; background:#f8f8f8; text-decoration:line-through; }}
  .slot-disabled input {{ pointer-events:none; }}
  .slots-container {{ max-height:400px; overflow-y:auto; border:1px solid #e2e8f0; border-radius:8px; padding:12px; margin:12px 0; }}

  /* Lab finder styles */
  .lab-selection {{ margin:12px 0; }}
  .btn-find-lab {{
    background:linear-gradient(135deg,#7c3aed,#a855f7);
    color:white; border:none; padding:12px 24px; border-radius:8px;
    font-size:14px; font-weight:600; cursor:pointer; transition:all .2s;
  }}
  .btn-find-lab:hover {{ transform:translateY(-1px); box-shadow:0 4px 12px rgba(124,58,237,0.3); }}
  .lab-selected-banner {{
    background:#f0fdf4; border:1px solid #059669; border-radius:8px;
    padding:12px 16px; display:flex; align-items:center; gap:8px; flex-wrap:wrap; font-size:14px;
  }}
  .lab-selected-banner strong {{ color:#059669; }}
  .btn-change-lab {{
    background:#e2e8f0; border:none; padding:4px 12px; border-radius:4px;
    font-size:12px; cursor:pointer; margin-left:8px;
  }}
  .btn-change-lab:hover {{ background:#cbd5e1; }}

  /* Modal */
  .modal-overlay {{
    position:fixed; top:0; left:0; right:0; bottom:0;
    background:rgba(0,0,0,0.6); z-index:9999;
    display:flex; align-items:center; justify-content:center;
  }}
  .modal-content {{
    background:white; border-radius:16px; width:95%; max-width:900px;
    max-height:90vh; overflow:hidden; display:flex; flex-direction:column;
    box-shadow:0 20px 60px rgba(0,0,0,0.3);
  }}
  .modal-header {{
    display:flex; justify-content:space-between; align-items:center;
    padding:20px 24px; border-bottom:1px solid #e2e8f0; background:#f8fafc;
  }}
  .modal-header h3 {{ font-size:18px; color:#1a1a2e; margin:0; }}
  .modal-close {{
    background:none; border:none; font-size:28px; cursor:pointer;
    color:#64748b; padding:0 4px; line-height:1;
  }}
  .modal-close:hover {{ color:#1a1a2e; }}
  .modal-body {{ padding:20px 24px; overflow-y:auto; flex:1; }}

  .lab-search-bar {{
    display:flex; gap:8px; margin-bottom:12px; flex-wrap:wrap;
  }}
  .lab-search-bar input {{
    flex:1; min-width:200px; padding:10px 14px; border:1px solid #d1d5db;
    border-radius:8px; font-size:14px; outline:none;
  }}
  .lab-search-bar input:focus {{ border-color:#7c3aed; box-shadow:0 0 0 3px rgba(124,58,237,0.1); }}
  .btn-search-loc, .btn-my-loc {{
    padding:10px 18px; border:none; border-radius:8px; font-size:13px;
    font-weight:600; cursor:pointer; white-space:nowrap;
  }}
  .btn-search-loc {{ background:#0033A1; color:white; }}
  .btn-search-loc:hover {{ background:#002880; }}
  .btn-my-loc {{ background:#059669; color:white; }}
  .btn-my-loc:hover {{ background:#047857; }}
  .lab-status {{
    font-size:13px; color:#64748b; margin-bottom:8px; min-height:20px;
  }}

  .lab-results {{ margin-top:12px; }}
  .lab-card {{
    border:1px solid #e2e8f0; border-radius:10px; padding:14px 18px;
    margin:8px 0; display:flex; justify-content:space-between;
    align-items:center; gap:12px; transition:all .15s; cursor:pointer;
  }}
  .lab-card:hover {{ border-color:#7c3aed; background:#faf5ff; }}
  .lab-card-info {{ flex:1; }}
  .lab-card-name {{ font-weight:600; font-size:15px; color:#1a1a2e; }}
  .lab-card-addr {{ font-size:13px; color:#64748b; margin:2px 0; }}
  .lab-card-meta {{ font-size:12px; color:#94a3b8; display:flex; gap:12px; margin-top:4px; }}
  .lab-card-meta .star {{ color:#f59e0b; }}
  .btn-select-lab {{
    background:#059669; color:white; border:none; padding:8px 20px;
    border-radius:6px; font-size:13px; font-weight:600; cursor:pointer;
    white-space:nowrap;
  }}
  .btn-select-lab:hover {{ background:#047857; }}
</style>
</head>
<body>
{body}

<!-- Leaflet JS -->
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
(function() {{
  // ── State ──
  var currentGapId = null;
  var currentMeasureId = null;
  var map = null;
  var markers = [];
  var userMarker = null;
  var userLat = null, userLng = null;
  var labResults = [];

  // Make functions globally accessible for onclick handlers
  window.openLabFinder = openLabFinder;
  window.closeLabModal = closeLabModal;
  window.searchByAddress = searchByAddress;
  window.useMyLocation = useMyLocation;
  window.selectLab = selectLab;

  // ── Open the lab finder modal for a specific gap ──
  function openLabFinder(gapId, measureId) {{
    currentGapId = gapId;
    currentMeasureId = measureId;
    document.getElementById('lab-modal').style.display = 'flex';
    document.getElementById('lab-results').innerHTML = '';
    document.getElementById('lab-status').textContent = 'Detecting your location...';
    document.getElementById('lab-location-input').value = '';

    // Init map if needed
    setTimeout(function() {{
      if (!map) {{
        map = L.map('lab-map').setView([37.7749, -122.4194], 12);
        L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
          attribution: '&copy; OpenStreetMap contributors',
          maxZoom: 19
        }}).addTo(map);
      }}
      map.invalidateSize();

      // Try geolocation
      if (userLat && userLng) {{
        setMapCenter(userLat, userLng);
        fetchNearbyLabs(userLat, userLng, measureId);
      }} else {{
        requestGeolocation();
      }}
    }}, 100);
  }}

  function closeLabModal() {{
    document.getElementById('lab-modal').style.display = 'none';
  }}

  // ── Geolocation ──
  function requestGeolocation() {{
    if (!navigator.geolocation) {{
      document.getElementById('lab-status').textContent =
        'Geolocation not supported. Please enter a location manually.';
      return;
    }}
    navigator.geolocation.getCurrentPosition(
      function(pos) {{
        userLat = pos.coords.latitude;
        userLng = pos.coords.longitude;
        setMapCenter(userLat, userLng);
        fetchNearbyLabs(userLat, userLng, currentMeasureId);
      }},
      function(err) {{
        document.getElementById('lab-status').textContent =
          'Location access denied. Please enter a location manually.';
      }},
      {{ enableHighAccuracy: true, timeout: 10000 }}
    );
  }}

  function useMyLocation() {{
    document.getElementById('lab-status').textContent = 'Detecting your location...';
    userLat = null;
    userLng = null;
    requestGeolocation();
  }}

  function setMapCenter(lat, lng) {{
    map.setView([lat, lng], 13);
    if (userMarker) map.removeLayer(userMarker);
    userMarker = L.marker([lat, lng], {{
      icon: L.divIcon({{
        className: '',
        html: '<div style="background:#0033A1;color:white;border-radius:50%;width:30px;height:30px;display:flex;align-items:center;justify-content:center;font-size:16px;border:3px solid white;box-shadow:0 2px 8px rgba(0,0,0,0.3);">&#128100;</div>',
        iconSize: [30, 30],
        iconAnchor: [15, 15]
      }})
    }}).addTo(map).bindPopup('<strong>Your Location</strong>');
  }}

  // ── Search by typed address using Google Geocoding via Places proxy ──
  function searchByAddress() {{
    var addr = document.getElementById('lab-location-input').value.trim();
    if (!addr) return;
    document.getElementById('lab-status').textContent = 'Searching location: ' + addr + '...';

    // Use Google Geocoding API through a fetch to our backend
    // We'll geocode on the server side — add a simple geocode endpoint
    fetch('/portal/api/geocode?address=' + encodeURIComponent(addr))
      .then(function(r) {{ return r.json(); }})
      .then(function(data) {{
        if (data.lat && data.lng) {{
          userLat = data.lat;
          userLng = data.lng;
          setMapCenter(userLat, userLng);
          fetchNearbyLabs(userLat, userLng, currentMeasureId);
        }} else {{
          document.getElementById('lab-status').textContent =
            'Could not find that location. Try a different address.';
        }}
      }})
      .catch(function() {{
        document.getElementById('lab-status').textContent = 'Geocoding failed. Try again.';
      }});
  }}

  // ── Fetch nearby labs from backend proxy ──
  function fetchNearbyLabs(lat, lng, measureId) {{
    document.getElementById('lab-status').textContent = 'Finding nearby labs and physicians...';
    clearMarkers();

    var url = '/portal/api/nearby-labs?lat=' + lat + '&lng=' + lng +
              '&measure_id=' + (measureId || '');

    fetch(url)
      .then(function(r) {{ return r.json(); }})
      .then(function(data) {{
        if (data.error) {{
          document.getElementById('lab-status').textContent = 'Error: ' + data.error;
          return;
        }}
        labResults = data.results || [];
        if (labResults.length === 0) {{
          document.getElementById('lab-status').textContent =
            'No labs found nearby. Try a different location or wider search.';
          document.getElementById('lab-results').innerHTML = '';
          return;
        }}
        document.getElementById('lab-status').textContent =
          'Found ' + labResults.length + ' nearby lab(s) and physician(s).';
        renderLabResults(labResults);
      }})
      .catch(function() {{
        document.getElementById('lab-status').textContent = 'Failed to fetch labs. Try again.';
      }});
  }}

  function clearMarkers() {{
    markers.forEach(function(m) {{ map.removeLayer(m); }});
    markers = [];
  }}

  // ── Render lab results as cards + map markers ──
  function renderLabResults(labs) {{
    var html = '';
    labs.forEach(function(lab, idx) {{
      // Add marker
      if (lab.lat && lab.lng) {{
        var marker = L.marker([lab.lat, lab.lng], {{
          icon: L.divIcon({{
            className: '',
            html: '<div style="background:#059669;color:white;border-radius:50%;width:28px;height:28px;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:bold;border:2px solid white;box-shadow:0 2px 6px rgba(0,0,0,0.3);">' + (idx + 1) + '</div>',
            iconSize: [28, 28],
            iconAnchor: [14, 14]
          }})
        }}).addTo(map).bindPopup(
          '<strong>' + lab.name + '</strong><br>' + (lab.address || '') +
          (lab.rating ? '<br>Rating: ' + lab.rating + ' &#11088;' : '')
        );
        markers.push(marker);
      }}

      var ratingHtml = lab.rating
        ? '<span class="star">&#11088; ' + lab.rating + '</span><span>(' + (lab.total_ratings || 0) + ' reviews)</span>'
        : '<span>No ratings</span>';
      var openHtml = lab.open_now === true
        ? '<span style="color:#059669;">Open Now</span>'
        : lab.open_now === false
          ? '<span style="color:#dc2626;">Closed</span>'
          : '';

      html += '<div class="lab-card" onclick="selectLab(' + idx + ')">' +
        '<div class="lab-card-info">' +
          '<div class="lab-card-name">' + (idx + 1) + '. ' + lab.name + '</div>' +
          '<div class="lab-card-addr">' + (lab.address || 'Address not available') + '</div>' +
          '<div class="lab-card-meta">' + ratingHtml + openHtml + '</div>' +
        '</div>' +
        '<button type="button" class="btn-select-lab" onclick="event.stopPropagation(); selectLab(' + idx + ')">Select</button>' +
      '</div>';
    }});
    document.getElementById('lab-results').innerHTML = html;

    // Fit map bounds to include all markers + user location
    if (markers.length > 0) {{
      var group = L.featureGroup(markers);
      if (userMarker) group.addLayer(userMarker);
      map.fitBounds(group.getBounds().pad(0.1));
    }}
  }}

  // ── Select a lab and populate hidden fields ──
  function selectLab(idx) {{
    var lab = labResults[idx];
    if (!lab || !currentGapId) return;

    // Populate hidden form fields
    document.getElementById('hid-lab-name-' + currentGapId).value = lab.name;
    document.getElementById('hid-lab-addr-' + currentGapId).value = lab.address || '';
    document.getElementById('hid-lab-pid-' + currentGapId).value = lab.place_id || '';
    document.getElementById('hid-lab-rating-' + currentGapId).value = lab.rating || '';

    // Fetch details (phone) in background
    if (lab.place_id) {{
      fetch('/portal/api/place-details?place_id=' + lab.place_id)
        .then(function(r) {{ return r.json(); }})
        .then(function(d) {{
          if (d.phone) {{
            document.getElementById('hid-lab-phone-' + currentGapId).value = d.phone;
          }}
        }}).catch(function() {{}});
    }}

    // Update the UI banner
    document.getElementById('lab-banner-' + currentGapId).style.display = 'flex';
    document.getElementById('lab-name-' + currentGapId).textContent = lab.name;
    document.getElementById('lab-addr-' + currentGapId).textContent = lab.address || '';
    document.getElementById('lab-prompt-' + currentGapId).style.display = 'none';

    // Close modal
    closeLabModal();
  }}

  // Allow Enter key in address input
  document.addEventListener('DOMContentLoaded', function() {{
    var inp = document.getElementById('lab-location-input');
    if (inp) {{
      inp.addEventListener('keydown', function(e) {{
        if (e.key === 'Enter') {{ e.preventDefault(); searchByAddress(); }}
      }});
    }}
  }});
}})();
</script>
</body>
</html>"""


# ── JSON API endpoint for auto-process (called from dashboard) ───────────────

@portal_bp.route("/api/v1/members/<member_id>/auto-process", methods=["GET"])
def auto_process_member(member_id):
    """
    Automated agent pipeline:
    1. detect_care_gaps (pure Python)
    2. Run 6-agent analysis (LLM)
    3. Send professional care gap analysis email with portal link
    Returns SSE-style JSON events for frontend progress tracking.
    """
    import json
    import logging
    from flask import Response, stream_with_context

    logger = logging.getLogger(__name__)

    def generate():
        try:
            # Step 1: Detect care gaps
            yield _sse({"step": "detect_gaps", "status": "running", "message": "Detecting care gaps..."})
            from src.care_gap_agents import detect_care_gaps
            gap_result = detect_care_gaps(member_id)
            yield _sse({"step": "detect_gaps", "status": "done",
                        "gaps_created": gap_result.get("gaps_created", []),
                        "compliant": gap_result.get("compliant", [])})

            profile = get_member_profile(member_id)
            if not profile:
                yield _sse({"step": "error", "message": "Member not found"})
                return

            gaps = get_member_open_gaps(member_id)
            name = profile.get("name", member_id)
            email = profile.get("email", "")

            if not gaps:
                yield _sse({"step": "complete", "status": "compliant",
                            "message": f"{name} is fully compliant. No email needed."})
                return

            # Persona sync: backfill any prior-screening / compliant measures
            # as Closed CareGaps in the reference DB so the timeline shows
            # them alongside the open ones. Idempotent — re-running is safe.
            try:
                from src.persona_sync import (
                    sync_compliant_measure, _find_screening_date_from_claims,
                )
                from src.care_gap_neo4j import get_member_claims_cpt_codes
                from src.hedis_golden_reference import HEDIS_MEASURES
                _claims_for_dates = get_member_claims_cpt_codes(member_id) or []
                for _cmid in (gap_result.get("compliant") or []):
                    _mdef = HEDIS_MEASURES.get(_cmid) or {}
                    _sdate = _find_screening_date_from_claims(_mdef, _claims_for_dates)
                    sync_compliant_measure(
                        member_id=member_id,
                        measure_id=_cmid,
                        measure_name=_mdef.get("name", _cmid),
                        screening_date=_sdate,
                    )
            except Exception as _comp_err:
                logger.warning(f"[AUTO-PROCESS] compliant sync skipped: {_comp_err}")

            # Persona sync: analysis starting
            try:
                from src.persona_sync import sync_analysis_started
                sync_analysis_started(member_id)
            except Exception:
                pass

            # Step 2: Run 6-agent analysis
            yield _sse({"step": "agent_analysis", "status": "running",
                        "message": "Running AI agent analysis..."})

            from src.care_gap_agents import CareGapAgentSystem
            agent_system = CareGapAgentSystem()
            agent_responses = {}
            for event_type, data in agent_system.validate_and_suggest_stream(member_id):
                if event_type == "agent_done":
                    agent_responses[data["agent"]] = data["content"]
                    yield _sse({"step": "agent_analysis", "agent": data["agent"],
                                "status": "done"})
                elif event_type == "agent_start":
                    yield _sse({"step": "agent_analysis", "agent": data["agent"],
                                "status": "running"})

            yield _sse({"step": "agent_analysis", "status": "done",
                        "message": "All agents completed."})

            # Persona sync: analysis complete
            try:
                from src.persona_sync import sync_analysis_complete
                summary = agent_responses.get("care_gap_agent", "")[:200]
                sync_analysis_complete(member_id, summary=summary)
            except Exception:
                pass

            # Step 3: Compose and send email
            email_actually_sent = False
            if not email:
                yield _sse({"step": "email", "status": "skipped",
                            "message": "No email on file — skipping email."})
            else:
                yield _sse({"step": "email", "status": "running",
                            "message": f"Sending analysis email to {email}..."})

                portal_url = get_portal_url(member_id)

                # Build the recommendation summary from agent output
                rec_text = agent_responses.get("recommendation_agent", "")
                care_gap_text = agent_responses.get("care_gap_agent", "")

                try:
                    _send_analysis_email(member_id, name, email, gaps, portal_url,
                                         rec_text, care_gap_text)
                    email_actually_sent = True
                    yield _sse({"step": "email", "status": "done",
                                "message": f"Email sent to {email}"})
                    # Persona sync: outreach sent
                    try:
                        from src.persona_sync import sync_outreach_sent
                        sync_outreach_sent(member_id, channel="Email")
                    except Exception:
                        pass
                except Exception as email_err:
                    logger.error(f"Email send failed: {email_err}", exc_info=True)
                    yield _sse({"step": "email", "status": "error",
                                "message": f"Email failed: {email_err}"})

            yield _sse({"step": "complete", "status": "success",
                        "message": f"Auto-process complete for {name}",
                        "gaps_count": len(gaps),
                        "email_sent": email_actually_sent})

        except Exception as exc:
            logger.exception("auto_process_member error")
            yield _sse({"step": "error", "message": str(exc)})

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
        },
    )


def _sse(data: dict) -> str:
    import json
    return f"data: {json.dumps(data)}\n\n"


def _send_analysis_email(member_id, name, email, gaps, portal_url,
                         recommendation_text, care_gap_text):
    """Send the care gap analysis email with human-readable treatment summary + PDF attachment."""
    import logging
    logger = logging.getLogger(__name__)

    from azure.communication.email import EmailClient
    from config.settings import settings as cfg
    from src.care_gap_neo4j import merge_email, get_member_profile
    from src.pdf_report import generate_member_report, _friendly
    import base64, re

    conn_str = cfg.azure_communication_connection_string
    sender = cfg.azure_communication_sender
    if not conn_str or not sender:
        raise RuntimeError(
            f"Azure email not configured: connection_string={'set' if conn_str else 'EMPTY'}, "
            f"sender={'set' if sender else 'EMPTY'}"
        )

    logger.info(f"[EMAIL] Starting email for member {member_id} to {email}")

    # ── Build human-readable gap cards (NO CPT/ICD codes) ──────────
    gap_cards_html = ""
    for g in gaps:
        what, why, action = _friendly(
            g.get("measure_id", ""),
            g.get("resolution_guide") or g.get("description", ""),
        )
        gap_cards_html += f"""
        <div style="background:#f8faff;border-left:4px solid #0033A1;padding:16px 20px;margin:12px 0;border-radius:0 8px 8px 0;">
          <h3 style="color:#0033A1;margin:0 0 8px;font-size:16px;">{what}</h3>
          <p style="color:#555;font-size:13px;margin:0 0 6px;"><strong>Why this matters:</strong> {why}</p>
          <p style="color:#333;font-size:13px;margin:0;"><strong>What to do:</strong> {action}</p>
        </div>"""

    # Clean up agent text for email display — strip ALL backend/clinical info
    def _clean_for_email(text, max_len=1200):
        if not text:
            return ""
        t = text[:max_len]
        # Remove markdown formatting
        t = re.sub(r'[*#`]', '', t)
        # Remove CPT codes, ICD codes, measure IDs, node references
        t = re.sub(r'CPT[\s:]*[\d,\s\-]+', '', t)
        t = re.sub(r'ICD[\-10]*[\s:]*[\w\.\,\s]+', '', t)
        t = re.sub(r'\b[A-Z]{2,4}-\d+\b', '', t)  # measure IDs like BCS-001
        t = re.sub(r'\bM\d{4,}\b', '', t)  # member IDs like M0001
        t = re.sub(r'\bcare_gap_id\b.*', '', t, flags=re.IGNORECASE)
        t = re.sub(r'\bCareGap\b', 'care gap', t)
        t = re.sub(r'\bQualityMeasure\b', 'screening', t)
        t = re.sub(r'\bCodeSet\b', '', t)
        t = re.sub(r'\bneo4j\b', '', t, flags=re.IGNORECASE)
        t = re.sub(r'\bgap_id\b', '', t, flags=re.IGNORECASE)
        t = re.sub(r'\bmeasure_id\b', '', t, flags=re.IGNORECASE)
        t = re.sub(r'\bnode\b', '', t, flags=re.IGNORECASE)
        t = re.sub(r'\{[^}]*\}', '', t)  # Remove JSON-like content
        t = re.sub(r'\s{2,}', ' ', t).strip()
        # Remove empty lines
        t = '\n'.join(line for line in t.split('\n') if line.strip())
        return t

    clean_rec = _clean_for_email(recommendation_text)
    clean_gap = _clean_for_email(care_gap_text)

    subject = f"Your Preventive Care Report - {len(gaps)} Recommended Screening(s)"

    html = f"""
<html><body style="font-family:Arial,sans-serif;color:#1a1a2e;max-width:700px;margin:auto;">
<div style="background:#0033A1;padding:24px 32px;border-radius:8px 8px 0 0;">
<h1 style="color:white;margin:0;font-size:22px;">HealthCare Management Portal</h1>
<p style="color:#b3c7f7;margin:4px 0 0;">Your Preventive Care Report</p>
</div>
<div style="border:1px solid #dce3f5;border-top:none;padding:32px;border-radius:0 0 8px 8px;">
<p style="font-size:16px;">Dear <strong>{name}</strong>,</p>
<p>Our care management team has reviewed your preventive care status. Based on nationally
recognized health guidelines, we recommend the following screenings to help keep you healthy.</p>

<h2 style="color:#0033A1;margin:24px 0 12px;font-size:18px;">Your Recommended Screenings</h2>
<p style="color:#666;font-size:13px;margin-bottom:8px;">You have <strong>{len(gaps)}</strong> preventive screening(s) that are due:</p>
{gap_cards_html}

{"<h2 style='color:#0033A1;margin:24px 0 12px;font-size:18px;'>Your Health Summary</h2><div style='background:#f0f4ff;padding:16px;border-radius:8px;font-size:14px;line-height:1.6;color:#333;'>" + clean_gap.strip() + "</div>" if clean_gap.strip() else ""}

{"<h2 style='color:#0033A1;margin:24px 0 12px;font-size:18px;'>What We Recommend</h2><div style='background:#f0fdf4;padding:16px;border-radius:8px;font-size:14px;line-height:1.6;color:#333;'>" + clean_rec.strip() + "</div>" if clean_rec.strip() else ""}

<div style="background:#fff8e1;border-radius:8px;padding:16px;margin:24px 0;">
  <p style="margin:0;font-size:13px;color:#7a5900;"><strong>Attached:</strong> Your complete Care Management Report (PDF) with full details about your health profile and recommended treatments.</p>
</div>

<div style="text-align:center;margin:32px 0;">
  <p style="font-size:16px;margin-bottom:16px;"><strong>Ready to schedule your screenings?</strong></p>
  <a href="{portal_url}" style="display:inline-block;background:#059669;color:white;padding:16px 40px;border-radius:8px;font-size:16px;font-weight:600;text-decoration:none;">
    Yes - Review &amp; Schedule Appointments
  </a>
  <p style="margin-top:12px;font-size:13px;color:#888;">
    Click above to choose your preferred appointment times at a facility near you.
  </p>
</div>

<hr style="border:none;border-top:1px solid #dce3f5;margin:24px 0;">
<p style="color:#888;font-size:12px;">
  This is an automated message from the HealthCare Management Portal.
  If you have questions, please contact your care management team.
</p>
</div>
</body></html>"""

    # ── Generate PDF attachment ────────────────────────────────────
    profile = {}
    try:
        profile = get_member_profile(member_id) or {}
    except Exception:
        logger.warning(f"[EMAIL] Could not fetch profile for {member_id}, continuing without")

    logger.info(f"[EMAIL] Generating PDF for {member_id}")
    pdf_bytes = generate_member_report(
        member_id=member_id,
        name=name,
        dob=profile.get("dob", ""),
        gender=profile.get("gender", ""),
        pcp_name=profile.get("pcp_name", ""),
        plan_id=profile.get("plan_id", ""),
        insurance_type=profile.get("insurance_type", ""),
        chronic_conditions=profile.get("chronic_conditions", ""),
        open_gaps=gaps,
        recommendation_text=recommendation_text,
        care_gap_text=care_gap_text,
    )
    pdf_b64 = base64.b64encode(pdf_bytes).decode("utf-8")
    logger.info(f"[EMAIL] PDF generated ({len(pdf_bytes)} bytes)")

    logger.info(f"[EMAIL] Sending via Azure: sender={sender}, to={email}")
    client = EmailClient.from_connection_string(conn_str)
    message = {
        "senderAddress": sender,
        "recipients": {"to": [{"address": email}]},
        "content": {
            "subject": subject,
            "html": html,
        },
        "attachments": [
            {
                "name": f"Care_Report_{member_id}.pdf",
                "contentType": "application/pdf",
                "contentInBase64": pdf_b64,
            }
        ],
    }
    import time as _time
    for _attempt in range(4):
        try:
            poller = client.begin_send(message)
            result = poller.result()
            break
        except Exception as _email_exc:
            if "TooManyRequests" in str(_email_exc) and _attempt < 3:
                _wait = max(1, (_attempt + 1) * 2)
                logger.warning(f"[EMAIL] Rate limited (attempt {_attempt + 1}/4), retrying in {_wait}s")
                _time.sleep(_wait)
            else:
                raise

    # Check Azure result status
    send_status = None
    if isinstance(result, dict):
        send_status = result.get("status")
    else:
        send_status = getattr(result, "status", None)

    logger.info(f"[EMAIL] Azure result status: {send_status}, full result: {result}")

    if send_status and str(send_status).lower() not in ("succeeded", "queued", "outfordelivery"):
        error_detail = ""
        if isinstance(result, dict) and result.get("error"):
            error_detail = f" - {result['error']}"
        raise RuntimeError(f"Azure email send status: {send_status}{error_detail}")

    # Persist email in Neo4j
    email_id = f"AUTO-ANALYSIS-{member_id}-{uuid.uuid4().hex[:8]}"
    merge_email(
        email_id=email_id,
        member_id=member_id,
        subject=subject,
        body=f"AI care report with {len(gaps)} recommended screenings. PDF attached.",
        from_email=sender,
        to_email=email,
        timestamp=datetime.now().isoformat(),
        direction="sent",
        is_read=True,
    )
    logger.info(f"[EMAIL] Email persisted in Neo4j: {email_id}")
