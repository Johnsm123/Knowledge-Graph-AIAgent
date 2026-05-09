"""
Generate cancer_screening_test_members.xlsx — 5 members covering every
relevant BCS / CCS / COL combination per the HEDIS MY2025 rulebook.

Today (2026-05-09) is the implicit measurement year reference.

Member design (rulebook-aligned):

  M1  Critical      F age 60  no priors                  → BCS + CCS + COL + AAP = 4 open
  M2  Needs Attn    F age 60  BCS + AAP priors           → CCS + COL = 2 open
  M3  Needs Attn    F age 35  no priors                  → CCS + AAP = 2 open  (age <45 → COL N/A, age <52 → BCS N/A)
  M4  Needs Attn    M age 55  no priors                  → COL + AAP = 2 open  (male → BCS/CCS N/A)
  M5  Compliant     F age 60  BCS + CCS + COL + AAP all priors → 0 open

Expected dashboard counts after upload:
  Critical = 1   Needs Attention = 3   Compliant = 1   Total = 5
"""
from __future__ import annotations
import os
import sys

import pandas as pd

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "cancer_screening_test_members.xlsx")

ROWS = [
    # ── M1 — CRITICAL: F60, no priors → BCS+CCS+COL all open
    {
        "Name": "Margaret Chen", "DOB": "1965-08-12", "Gender": "F",
        "Email": "ajohnsm2020@gmail.com", "Phone": "15551110001",
        "PCPID": "P1001", "PlanID": "PLAN-001", "ZIP": "10001",
        "ChronicConditions": "",
        "InsuranceType": "Commercial",
        "EnrollmentStart": "2024-01-01", "EnrollmentEnd": "2026-12-31",
        "PriorScreenings": "",
        "HeightCm": 162, "WeightKg": 65,
        "SmokingStatus": "Never", "AlcoholUse": "Occasional",
        "ExerciseFrequency": "2-3x/week", "DietType": "Balanced",
        "SleepHoursAvg": 7, "StressLevel": "Low",
        "LifestyleNotes": "Walks daily; no current concerns.",
        "FamilyHistory": "Mother|true|82|None;Father|false|78|Heart Disease",
        "PastConditions": "Seasonal allergies|2010|Resolved|Mild",
        "CurrentConditions": "",
        "Surgeries": "",
        "Allergies": "Penicillin|Mild|Rash",
        "Medications": "Multivitamin|1 tab|2018|General wellness",
        "Immunizations": "Influenza|2025;Tdap|2022",
    },
    # ── M2 — NEEDS ATTENTION: F60, BCS prior → CCS+COL open (2)
    {
        "Name": "Sandra Patel", "DOB": "1965-10-04", "Gender": "F",
        "Email": "ajohnsm2020@gmail.com", "Phone": "15551110002",
        "PCPID": "P1002", "PlanID": "PLAN-001", "ZIP": "10002",
        "ChronicConditions": "",
        "InsuranceType": "Commercial",
        "EnrollmentStart": "2024-01-01", "EnrollmentEnd": "2026-12-31",
        # Mammogram in last 24 months → BCS satisfied; recent PCP visit → AAP satisfied
        "PriorScreenings": "BCS:2025-09-15;AAP:2026-02-10",
        "HeightCm": 158, "WeightKg": 62,
        "SmokingStatus": "Never", "AlcoholUse": "None",
        "ExerciseFrequency": "Daily", "DietType": "Mediterranean",
        "SleepHoursAvg": 8, "StressLevel": "Low",
        "LifestyleNotes": "Active retiree; volunteers weekly.",
        "FamilyHistory": "Mother|true|85|None;Sister|true|62|Breast Cancer",
        "PastConditions": "Vitamin D deficiency|2019|Resolved|Supplementation",
        "CurrentConditions": "",
        "Surgeries": "",
        "Allergies": "",
        "Medications": "Vitamin D3|2000 IU|2019|Bone health",
        "Immunizations": "Influenza|2025;Pneumococcal|2024;Shingles|2023",
    },
    # ── M3 — NEEDS ATTENTION: F35, no priors → CCS open only (1)
    {
        "Name": "Emily Rodriguez", "DOB": "1990-11-22", "Gender": "F",
        "Email": "ajohnsm2020@gmail.com", "Phone": "15551110003",
        "PCPID": "P1003", "PlanID": "PLAN-001", "ZIP": "10003",
        "ChronicConditions": "",
        "InsuranceType": "Commercial",
        "EnrollmentStart": "2024-01-01", "EnrollmentEnd": "2026-12-31",
        "PriorScreenings": "",
        "HeightCm": 165, "WeightKg": 60,
        "SmokingStatus": "Never", "AlcoholUse": "Occasional",
        "ExerciseFrequency": "3-4x/week", "DietType": "Balanced",
        "SleepHoursAvg": 7, "StressLevel": "Moderate",
        "LifestyleNotes": "Software engineer; sedentary work, runs on weekends.",
        "FamilyHistory": "Mother|true|65|None;Father|true|68|Hypertension",
        "PastConditions": "",
        "CurrentConditions": "",
        "Surgeries": "",
        "Allergies": "",
        "Medications": "",
        "Immunizations": "Influenza|2025;Tdap|2021;HPV|2010",
    },
    # ── M4 — NEEDS ATTENTION: M55, no priors → COL open only (1)
    {
        "Name": "Daniel Williams", "DOB": "1970-06-30", "Gender": "M",
        "Email": "ajohnsm2020@gmail.com", "Phone": "15551110004",
        "PCPID": "P1004", "PlanID": "PLAN-001", "ZIP": "10004",
        "ChronicConditions": "",
        "InsuranceType": "Commercial",
        "EnrollmentStart": "2024-01-01", "EnrollmentEnd": "2026-12-31",
        "PriorScreenings": "",
        "HeightCm": 178, "WeightKg": 82,
        "SmokingStatus": "Former", "AlcoholUse": "Moderate",
        "ExerciseFrequency": "2x/week", "DietType": "Mixed",
        "SleepHoursAvg": 6, "StressLevel": "Moderate",
        "LifestyleNotes": "Quit smoking 2018; occasional gym workouts.",
        "FamilyHistory": "Father|false|72|Colorectal Cancer;Mother|true|78|None",
        "PastConditions": "Tobacco use disorder|2018|Resolved|Quit successfully",
        "CurrentConditions": "",
        "Surgeries": "Appendectomy|2002|Uneventful",
        "Allergies": "",
        "Medications": "",
        "Immunizations": "Influenza|2025;Tdap|2020",
    },
    # ── M5 — COMPLIANT: F60, all three priors → 0 open
    {
        "Name": "Linda Johnson", "DOB": "1965-04-15", "Gender": "F",
        "Email": "ajohnsm2020@gmail.com", "Phone": "15551110005",
        "PCPID": "P1005", "PlanID": "PLAN-001", "ZIP": "10005",
        "ChronicConditions": "",
        "InsuranceType": "Commercial",
        "EnrollmentStart": "2024-01-01", "EnrollmentEnd": "2026-12-31",
        # BCS within 24 mo, CCS within 36 mo, COL colonoscopy within 10 yr, AAP within 12 mo
        "PriorScreenings": "BCS:2025-09-10;CCS:2024-04-22;COL:2020-06-18;AAP:2025-11-05",
        "HeightCm": 160, "WeightKg": 63,
        "SmokingStatus": "Never", "AlcoholUse": "Occasional",
        "ExerciseFrequency": "Daily", "DietType": "Mediterranean",
        "SleepHoursAvg": 8, "StressLevel": "Low",
        "LifestyleNotes": "Retired teacher; engaged with primary care annually.",
        "FamilyHistory": "Mother|true|88|None;Father|true|85|None",
        "PastConditions": "Hypothyroidism|2010|Resolved|Levothyroxine",
        "CurrentConditions": "",
        "Surgeries": "Cataract|2023|Right eye",
        "Allergies": "Sulfa|Mild|Rash",
        "Medications": "Vitamin D3|1000 IU|2020|Bone health",
        "Immunizations": "Influenza|2025;Pneumococcal|2024;Shingles|2024;Tdap|2022",
    },
]


def main() -> None:
    df = pd.DataFrame(ROWS)
    out = OUT
    try:
        df.to_excel(out, index=False)
    except PermissionError:
        # File is open in Excel — write to a timestamped sibling instead.
        import datetime as _dt
        stamp = _dt.datetime.now().strftime("%H%M%S")
        out = OUT.replace(".xlsx", f"_{stamp}.xlsx")
        df.to_excel(out, index=False)
        print(f"NOTE: {OUT} was locked (open in Excel); wrote to {out} instead.")
    print(f"Wrote {len(df)} test members to: {out}")
    print()
    print("Expected detection per HEDIS MY2025 rulebook (scope BCS,CCS,COL,AAP; today = 2026-05-09):")
    print("  M1 Margaret Chen   F60  -> BCS + CCS + COL + AAP = 4 open  -> CRITICAL")
    print("  M2 Sandra Patel    F60  -> CCS + COL             = 2 open  -> NEEDS ATTENTION")
    print("  M3 Emily Rodriguez F35  -> CCS + AAP             = 2 open  -> NEEDS ATTENTION")
    print("  M4 Daniel Williams M55  -> COL + AAP             = 2 open  -> NEEDS ATTENTION")
    print("  M5 Linda Johnson   F60  -> none                  = 0 open  -> COMPLIANT")
    print()
    print("Dashboard pill counts: Critical=1  Needs Attention=3  Compliant=1  All=5")


if __name__ == "__main__":
    sys.exit(main() or 0)
