"""
Generate a member-friendly PDF care management report.

Uses fpdf2 to produce a professional PDF with:
  - Member profile header
  - Open care gaps with plain-language treatment descriptions
  - Appointment schedule
  - Outreach history summary
  - No CPT / ICD / clinical codes (those are for providers only)
"""

import io
import re
import textwrap
from datetime import datetime
from fpdf import FPDF


def _safe(text: str) -> str:
    """Replace Unicode characters that latin-1 core fonts cannot render."""
    text = (
        text
        .replace("\u2014", "--")   # em dash
        .replace("\u2013", "-")    # en dash
        .replace("\u2018", "'")    # left single quote
        .replace("\u2019", "'")    # right single quote
        .replace("\u201c", '"')    # left double quote
        .replace("\u201d", '"')    # right double quote
        .replace("\u2026", "...")  # ellipsis
        .replace("\u2022", "-")    # bullet
        .replace("\u00a0", " ")    # non-breaking space
        .replace("\u2190", "<-")   # left arrow
        .replace("\u2192", "->")   # right arrow
        .replace("\u2191", "^")    # up arrow
        .replace("\u2193", "v")    # down arrow
        .replace("\u2794", "->")   # heavy right arrow
        .replace("\u27a4", "->")   # black right arrowhead
        .replace("\u2023", ">")    # triangular bullet
        .replace("\u25cf", "-")    # black circle
        .replace("\u25cb", "o")    # white circle
        .replace("\u2713", "[x]")  # check mark
        .replace("\u2717", "[ ]")  # ballot x
        .replace("\u2605", "*")    # black star
        .replace("\u2606", "*")    # white star
        .replace("\u00b7", "-")    # middle dot
    )
    # Strip any remaining non-latin-1 characters
    return text.encode("latin-1", errors="replace").decode("latin-1")


# ── Human-readable treatment descriptions keyed by measure_id ─────────────
# Falls back to the QualityMeasure.description stored in Neo4j when the
# measure_id is not listed here.
_FRIENDLY_TREATMENTS = {
    "BCS": {
        "what": "Breast Cancer Screening (Mammogram)",
        "why": (
            "Mammograms can detect breast cancer early -- often before any symptoms appear."
            "Early detection gives you the best chance for successful treatment."
        ),
        "action": (
            "Schedule a screening mammogram at a radiology or imaging center near you. "
            "The procedure takes about 20 minutes and is covered by most preventive care plans."
        ),
    },
    "COL": {
        "what": "Colorectal Cancer Screening",
        "why": (
            "Colorectal screening can find polyps before they become cancerous. "
            "It is one of the most effective cancer-prevention tools available."
        ),
        "action": (
            "You can choose between a colonoscopy (recommended every 10 years), "
            "a stool-based test such as FIT or FIT-DNA (every 1-3 years), or a "
            "flexible sigmoidoscopy (every 5 years). Talk to your doctor about "
            "which option is right for you."
        ),
    },
    "CCS": {
        "what": "Cervical Cancer Screening",
        "why": (
            "Regular cervical screening (Pap test or HPV test) can detect changes "
            "in cervical cells before they become cancer."
        ),
        "action": (
            "Visit your OB/GYN or primary care provider for a Pap test, HPV test, "
            "or a combined Pap + HPV co-test depending on your age and prior results."
        ),
    },
    "GSD": {
        "what": "Diabetes - Blood Sugar (HbA1c) Check",
        "why": (
            "An HbA1c test shows your average blood sugar level over the past 2-3 months. "
            "Keeping HbA1c in range reduces the risk of serious diabetes complications."
        ),
        "action": (
            "Schedule a lab visit for an HbA1c blood draw. Your doctor will review the "
            "result and adjust your treatment plan if needed."
        ),
    },
    "EED": {
        "what": "Diabetes - Eye Exam",
        "why": (
            "Diabetes can damage the small blood vessels in your eyes (diabetic retinopathy). "
            "An annual dilated eye exam catches these changes early."
        ),
        "action": (
            "Book a dilated retinal eye exam with an ophthalmologist or optometrist. "
            "The exam is quick, painless, and covered under your preventive benefits."
        ),
    },
    "KED": {
        "what": "Diabetes - Kidney Health Evaluation",
        "why": (
            "Diabetes is a leading cause of kidney disease. A simple blood and urine test "
            "can check how well your kidneys are filtering and whether you need early treatment."
        ),
        "action": (
            "Ask your doctor to order a kidney panel (eGFR blood test and urine albumin test). "
            "Both are done at a routine lab visit."
        ),
    },
    "BPD": {
        "what": "Diabetes - Blood Pressure Control",
        "why": (
            "High blood pressure combined with diabetes significantly increases the risk "
            "of heart disease and stroke. Regular monitoring keeps you on track."
        ),
        "action": (
            "Have your blood pressure checked at your next doctor visit. If it is elevated, "
            "your doctor may recommend lifestyle changes or medication adjustments."
        ),
    },
}


def _friendly(measure_id: str, resolution_guide: str | None):
    """Return (what, why, action) for a given measure."""
    entry = _FRIENDLY_TREATMENTS.get(measure_id)
    if entry:
        return entry["what"], entry["why"], entry["action"]
    # Fallback: use the resolution guide stored in Neo4j
    guide = (resolution_guide or "").strip()
    # Strip any CPT/ICD references from the fallback text
    guide = re.sub(r'CPT\s*[\d,\s\-]+', '', guide)
    guide = re.sub(r'ICD[\-10]*\s*[\w\.\,\s]+', '', guide)
    guide = re.sub(r'\s{2,}', ' ', guide).strip()
    what = measure_id
    why = guide if guide else "This screening is recommended based on your age and health profile."
    action = "Please schedule this screening at a facility near you."
    return what, why, action


class _PDF(FPDF):
    """Custom PDF with branded header / footer."""

    def header(self):
        self.set_fill_color(0, 51, 161)   # #0033A1
        self.rect(0, 0, 210, 32, "F")
        self.set_font("Helvetica", "B", 16)
        self.set_text_color(255, 255, 255)
        self.set_y(8)
        self.cell(0, 8, "HealthCare Management Portal", align="C")
        self.ln(7)
        self.set_font("Helvetica", "", 10)
        self.set_text_color(200, 215, 255)
        self.cell(0, 6, "Personalized Care Management Report", align="C")
        self.ln(14)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10,
                  f"Confidential | Generated {datetime.now().strftime('%B %d, %Y')} | Page {self.page_no()}/{{nb}}",
                  align="C")


def generate_member_report(
    *,
    member_id: str,
    name: str,
    dob: str = "",
    gender: str = "",
    pcp_name: str = "",
    plan_id: str = "",
    insurance_type: str = "",
    chronic_conditions: str = "",
    open_gaps: list[dict],
    appointments: list[dict] | None = None,
    outreach: list[dict] | None = None,
    recommendation_text: str = "",
    care_gap_text: str = "",
) -> bytes:
    """
    Build and return a PDF (as bytes) for one member.

    The report is written in plain language — no CPT, ICD, or HEDIS codes —
    so that the member can understand their recommended treatments.
    """
    # Sanitize all string inputs for latin-1 font compatibility
    name = _safe(str(name))
    member_id = _safe(str(member_id))
    dob = _safe(str(dob))
    gender = _safe(str(gender))
    pcp_name = _safe(str(pcp_name))
    plan_id = _safe(str(plan_id))
    insurance_type = _safe(str(insurance_type))
    chronic_conditions = _safe(str(chronic_conditions))
    recommendation_text = _safe(str(recommendation_text))
    care_gap_text = _safe(str(care_gap_text))

    pdf = _PDF()
    pdf.alias_nb_pages()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=20)

    # ── 1. Member Profile ──────────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(0, 51, 161)
    pdf.cell(0, 10, "Member Profile", ln=True)
    pdf.set_draw_color(0, 51, 161)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(3)

    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(40, 40, 40)

    profile_rows = [
        ("Name", name),
        ("Member ID", member_id),
    ]
    if dob:
        profile_rows.append(("Date of Birth", dob))
    if gender:
        profile_rows.append(("Gender", gender))
    if pcp_name:
        profile_rows.append(("Primary Care Provider", pcp_name))
    if plan_id:
        profile_rows.append(("Benefit Plan", plan_id))
    if insurance_type:
        profile_rows.append(("Insurance", insurance_type))
    if chronic_conditions:
        profile_rows.append(("Chronic Conditions", chronic_conditions))

    for label, value in profile_rows:
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(55, 7, f"{label}:", ln=False)
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 7, str(value), ln=True)
    pdf.ln(4)

    # ── 2. Recommended Screenings & Treatments ─────────────────────────────
    if open_gaps:
        pdf.set_font("Helvetica", "B", 14)
        pdf.set_text_color(0, 51, 161)
        pdf.cell(0, 10, "Recommended Screenings & Treatments", ln=True)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(3)

        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(40, 40, 40)
        pdf.multi_cell(0, 5,
            "Based on nationally recognized HEDIS quality guidelines and your health profile, "
            "the following preventive screenings are recommended for you. Completing these on "
            "time helps keep you healthy and prevents serious conditions.\n")
        pdf.ln(2)

        for i, gap in enumerate(open_gaps, 1):
            what, why, action = _friendly(
                gap.get("measure_id", ""),
                gap.get("resolution_guide") or gap.get("description", ""),
            )
            what, why, action = _safe(what), _safe(why), _safe(action)

            # Gap title
            pdf.set_fill_color(240, 244, 255)
            pdf.set_font("Helvetica", "B", 11)
            pdf.set_text_color(0, 51, 161)
            pdf.cell(0, 8, f"  {i}. {what}", ln=True, fill=True)
            pdf.ln(1)

            # Why this matters
            pdf.set_font("Helvetica", "B", 9)
            pdf.set_text_color(80, 80, 80)
            pdf.cell(0, 5, "Why this matters:", ln=True)
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(40, 40, 40)
            pdf.multi_cell(0, 4.5, why)
            pdf.ln(1)

            # What you need to do
            pdf.set_font("Helvetica", "B", 9)
            pdf.set_text_color(80, 80, 80)
            pdf.cell(0, 5, "What you need to do:", ln=True)
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(40, 40, 40)
            pdf.multi_cell(0, 4.5, action)

            # Lookback info
            lookback = gap.get("lookback_months")
            if lookback:
                pdf.set_font("Helvetica", "I", 8)
                pdf.set_text_color(120, 120, 120)
                pdf.cell(0, 5, f"Screening window: within the past {lookback} months", ln=True)

            pdf.ln(4)

    # ── 3. AI Care Summary ──────────────────────────────────────────────
    clean_rec = re.sub(r'[*#`]', '', recommendation_text[:2000]).strip() if recommendation_text else ""
    clean_gap = re.sub(r'[*#`]', '', care_gap_text[:1500]).strip() if care_gap_text else ""
    # Remove any CPT/ICD codes from agent text
    for txt_field in [clean_rec, clean_gap]:
        txt_field = re.sub(r'CPT[\s:]*[\d,\s\-]+', '', txt_field)
        txt_field = re.sub(r'ICD[\-10]*[\s:]*[\w\.\,\s]+', '', txt_field)

    if clean_gap or clean_rec:
        pdf.set_font("Helvetica", "B", 14)
        pdf.set_text_color(0, 51, 161)
        pdf.cell(0, 10, "AI Care Management Summary", ln=True)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(3)

        if clean_gap:
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_text_color(60, 60, 60)
            pdf.cell(0, 6, "Analysis:", ln=True)
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(40, 40, 40)
            # Strip codes from display text
            display_gap = re.sub(r'CPT[\s:]*[\d,\s\-]+', '', clean_gap)
            display_gap = re.sub(r'ICD[\-10]*[\s:]*[\w\.\,\s]+', '', display_gap)
            pdf.multi_cell(0, 4.5, display_gap.strip())
            pdf.ln(3)

        if clean_rec:
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_text_color(60, 60, 60)
            pdf.cell(0, 6, "Recommendations:", ln=True)
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(40, 40, 40)
            display_rec = re.sub(r'CPT[\s:]*[\d,\s\-]+', '', clean_rec)
            display_rec = re.sub(r'ICD[\-10]*[\s:]*[\w\.\,\s]+', '', display_rec)
            pdf.multi_cell(0, 4.5, display_rec.strip())
            pdf.ln(3)

    # ── 4. Scheduled Appointments ──────────────────────────────────────────
    if appointments:
        pdf.set_font("Helvetica", "B", 14)
        pdf.set_text_color(0, 51, 161)
        pdf.cell(0, 10, "Scheduled Appointments", ln=True)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(3)

        for appt in appointments:
            pdf.set_fill_color(240, 253, 244)
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_text_color(5, 150, 105)
            screening = _safe(str(appt.get("screening_name") or appt.get("measure_id", "Screening")))
            pdf.cell(0, 7, f"  {screening}", ln=True, fill=True)
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(40, 40, 40)

            date_str = _safe(str(appt.get("appointment_date", "")))
            time_str = _safe(str(appt.get("appointment_time", "")))
            if date_str:
                pdf.cell(0, 5, f"    Date: {date_str}    Time: {time_str}", ln=True)
            lab = _safe(str(appt.get("lab_specialist", "")))
            loc = _safe(str(appt.get("lab_location", "")))
            if lab or loc:
                pdf.cell(0, 5, f"    Facility: {lab}  |  Location: {loc}", ln=True)
            status = _safe(str(appt.get("status", "Scheduled")))
            pdf.cell(0, 5, f"    Status: {status}", ln=True)
            pdf.ln(3)

    # ── 5. Outreach History ────────────────────────────────────────────────
    if outreach:
        pdf.set_font("Helvetica", "B", 14)
        pdf.set_text_color(0, 51, 161)
        pdf.cell(0, 10, "Outreach History", ln=True)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(3)

        # Table header
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_fill_color(0, 51, 161)
        pdf.set_text_color(255, 255, 255)
        pdf.cell(35, 7, "Date", border=1, fill=True)
        pdf.cell(30, 7, "Channel", border=1, fill=True)
        pdf.cell(60, 7, "Screening", border=1, fill=True)
        pdf.cell(30, 7, "Status", border=1, fill=True, ln=True)

        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(40, 40, 40)
        for o in outreach[:15]:  # Cap at 15 rows
            pdf.cell(35, 6, _safe(str(o.get("date", "")))[:10], border=1)
            pdf.cell(30, 6, _safe(str(o.get("channel", ""))), border=1)
            pdf.cell(60, 6, _safe(str(o.get("measure_name", "")))[:35], border=1)
            pdf.cell(30, 6, _safe(str(o.get("status", ""))), border=1, ln=True)
        pdf.ln(4)

    # ── 6. Important Note ──────────────────────────────────────────────────
    pdf.set_fill_color(255, 248, 225)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(120, 80, 0)
    pdf.cell(0, 7, "  Important Information", ln=True, fill=True)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(80, 60, 0)
    pdf.multi_cell(0, 4.5,
        "This report is generated by our care management system based on nationally "
        "recognized HEDIS quality measures. It is meant to help you stay on top of your preventive care. "
        "Please consult your primary care provider for any medical decisions. "
        "If you have questions, contact your care management team.")
    pdf.ln(4)

    # ── Return PDF bytes ───────────────────────────────────────────────────
    return pdf.output()
