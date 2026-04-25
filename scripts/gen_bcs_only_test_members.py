"""
Generate an Excel file of test members designed so the rules engine
detects ONLY the BCS (Breast Cancer Screening) care gap.

Reasoning per measure (per HEDIS golden reference):
  BCS  -> Female, age 52-74, lookback 24 months. We TRIGGER this by
          giving each member NO prior mammogram claim.
  CCS  -> Female, age 21-64. Avoided by age >= 65.
  CHL  -> Female, age 16-24.  Avoided by age >= 65.
  COL  -> Any gender, age 45-75. Avoided by adding a recent COL
          (colonoscopy) claim via PriorScreenings (lookback 120 months).
  AAP  -> 20+, any. Avoided by adding a recent AAP (office visit)
          claim via PriorScreenings (lookback 12 months).
  GSD/EED/KED/BPD -> require Diabetes (E08-E13). Avoided by NOT
          including diabetes in ChronicConditions.
  CBP  -> requires Hypertension (I10). Avoided by NOT including
          hypertension in ChronicConditions.

Output: bulk_upload_BCS_only_test.xlsx in project root.
"""
import os
from datetime import datetime, timedelta
import pandas as pd

TODAY = datetime(2026, 4, 25)


def dob_for_age(years: int) -> str:
    return (TODAY.replace(year=TODAY.year - years) - timedelta(days=120)).strftime("%Y-%m-%d")


def recent(days_ago: int) -> str:
    return (TODAY - timedelta(days=days_ago)).strftime("%Y-%m-%d")


# 10 female members, ages 65-74, no diabetes/hypertension, COL+AAP completed.
# Extended record (lifestyle/family/past/surgeries/allergies/meds) is populated
# but kept SAFE — nothing here introduces an ICD that would (a) trigger another
# measure (E08-E13 diabetes / I10 HTN) or (b) exclude BCS itself
# (mastectomy / pregnancy / hospice / palliative).
members = [
    {
        "Name": "Patricia Hall",         "age": 67, "ZIP": "10001",
        "Email": "ajohnsm2020@gmail.com", "Phone": "+15551110001",
        "Conditions": "Osteoarthritis",  "PCPID": "P1001",
        "LifestyleNotes": "Walks 30 minutes daily; retired teacher.",
        "FamilyHistory": "Mother|false|82|Stroke;Father|false|79|Heart Disease;Sister|true|65|Osteoarthritis",
        "PastConditions": "Seasonal allergies|2010|Resolved|Pollen-triggered;Iron deficiency anemia|2018|Resolved|Iron supplements 6 months",
        "CurrentConditions": "Osteoarthritis (knees)|2019|Managed with NSAIDs as needed",
        "Surgeries": "Right knee arthroscopy|2016|Outpatient",
        "Allergies": "Penicillin|Moderate|Hives;Latex|Mild|Skin irritation",
        "Medications": "Acetaminophen|500mg|2019|Joint pain;Vitamin D3|2000 IU|2020|Bone health",
    },
    {
        "Name": "Linda Carter",          "age": 70, "ZIP": "10002",
        "Email": "ajohnsm2020@gmail.com", "Phone": "+15551110002",
        "Conditions": "Hypothyroidism",  "PCPID": "P1002",
        "LifestyleNotes": "Morning yoga, vegetarian diet for 15 years.",
        "FamilyHistory": "Mother|true|92|Hypothyroidism;Father|false|85|Stroke;Brother|true|72|Hypothyroidism",
        "PastConditions": "Vitamin B12 deficiency|2015|Resolved|Oral supplementation",
        "CurrentConditions": "Hypothyroidism|2012|Stable on levothyroxine",
        "Surgeries": "Cataract removal (right eye)|2022|Lens implant successful",
        "Allergies": "Sulfa drugs|Severe|Rash and swelling",
        "Medications": "Levothyroxine|75mcg|2012|Hypothyroidism;Calcium carbonate|600mg|2018|Bone health",
    },
    {
        "Name": "Margaret Ross",         "age": 65, "ZIP": "10003",
        "Email": "ajohnsm2020@gmail.com", "Phone": "+15551110003",
        "Conditions": "",                "PCPID": "P1003",
        "LifestyleNotes": "Active gardener; no medical issues currently.",
        "FamilyHistory": "Mother|true|88|None;Father|false|81|Heart Disease;Sister|true|62|None",
        "PastConditions": "Mild concussion|2019|Resolved|Recovered fully after 2 weeks",
        "CurrentConditions": "",
        "Surgeries": "",
        "Allergies": "Shellfish|Moderate|Hives and itching",
        "Medications": "Multivitamin|1 tab|2018|General wellness",
    },
    {
        "Name": "Susan Bennett",         "age": 73, "ZIP": "10004",
        "Email": "ajohnsm2020@gmail.com", "Phone": "+15551110004",
        "Conditions": "Osteoporosis",    "PCPID": "P1004",
        "LifestyleNotes": "Light strength training twice a week; physical therapy sessions ongoing.",
        "FamilyHistory": "Mother|false|86|Osteoporosis;Father|false|83|Heart Disease;Sister|true|70|Osteoarthritis",
        "PastConditions": "Wrist fracture|2017|Resolved|Cast for 6 weeks",
        "CurrentConditions": "Osteoporosis|2018|On bisphosphonate therapy",
        "Surgeries": "Right hip replacement|2020|Recovered well",
        "Allergies": "Aspirin|Mild|GI upset",
        "Medications": "Alendronate|70mg weekly|2018|Osteoporosis;Vitamin D3|2000 IU|2018|Bone health;Calcium citrate|1200mg|2018|Bone health",
    },
    {
        "Name": "Karen Mitchell",        "age": 68, "ZIP": "10005",
        "Email": "ajohnsm2020@gmail.com", "Phone": "+15551110005",
        "Conditions": "GERD",            "PCPID": "P1005",
        "LifestyleNotes": "Avoids spicy foods and late-night meals; sleeps with elevated headboard.",
        "FamilyHistory": "Mother|true|90|GERD;Father|false|78|Stroke;Brother|true|65|GERD",
        "PastConditions": "H. pylori infection|2014|Resolved|Triple therapy",
        "CurrentConditions": "GERD|2014|Managed with PPI",
        "Surgeries": "Appendectomy|1985|Standard recovery",
        "Allergies": "",
        "Medications": "Omeprazole|20mg|2014|GERD;Multivitamin|1 tab|2015|General wellness",
    },
    {
        "Name": "Barbara Foster",        "age": 71, "ZIP": "10006",
        "Email": "ajohnsm2020@gmail.com", "Phone": "+15551110006",
        "Conditions": "",                "PCPID": "P1006",
        "LifestyleNotes": "Daily 45-minute walks; volunteers at local library.",
        "FamilyHistory": "Mother|false|84|Heart Disease;Father|false|80|Stroke;Sister|true|68|None",
        "PastConditions": "Vitamin D deficiency|2019|Resolved|Supplementation",
        "CurrentConditions": "",
        "Surgeries": "Tonsillectomy|1962|Childhood",
        "Allergies": "Bee stings|Moderate|Localized swelling",
        "Medications": "Vitamin D3|1000 IU|2019|Bone health",
    },
    {
        "Name": "Nancy Sullivan",        "age": 66, "ZIP": "10007",
        "Email": "ajohnsm2020@gmail.com", "Phone": "+15551110007",
        "Conditions": "Allergic Rhinitis", "PCPID": "P1007",
        "LifestyleNotes": "Uses HEPA air filter at home; avoids outdoor activities during high pollen days.",
        "FamilyHistory": "Mother|true|89|Allergic Rhinitis;Father|false|82|Heart Disease;Sister|true|63|Asthma",
        "PastConditions": "Sinusitis (recurrent)|2015|Resolved|Course of antibiotics",
        "CurrentConditions": "Allergic Rhinitis|2010|Seasonal antihistamines",
        "Surgeries": "",
        "Allergies": "Pollen|Moderate|Sneezing and congestion;Dust mites|Mild|Nasal congestion",
        "Medications": "Loratadine|10mg|2010|Allergic Rhinitis;Fluticasone nasal spray|50mcg|2012|Allergic Rhinitis",
    },
    {
        "Name": "Helen Brooks",          "age": 74, "ZIP": "10008",
        "Email": "ajohnsm2020@gmail.com", "Phone": "+15551110008",
        "Conditions": "Osteoarthritis",  "PCPID": "P1008",
        "LifestyleNotes": "Water aerobics three times a week; uses cane for long walks.",
        "FamilyHistory": "Mother|false|87|Osteoarthritis;Father|false|85|Heart Disease;Brother|true|70|Osteoarthritis",
        "PastConditions": "Frozen shoulder (left)|2018|Resolved|Physical therapy",
        "CurrentConditions": "Osteoarthritis (knees and hips)|2015|Pain managed conservatively",
        "Surgeries": "Left knee arthroscopy|2019|Cleaned up cartilage",
        "Allergies": "Iodine contrast|Moderate|Rash",
        "Medications": "Acetaminophen|650mg|2015|Joint pain;Glucosamine|1500mg|2017|Joint health;Vitamin D3|2000 IU|2018|Bone health",
    },
    {
        "Name": "Sandra Powell",         "age": 69, "ZIP": "10009",
        "Email": "ajohnsm2020@gmail.com", "Phone": "+15551110009",
        "Conditions": "",                "PCPID": "P1009",
        "LifestyleNotes": "Cycling enthusiast; rides 20 miles per weekend.",
        "FamilyHistory": "Mother|true|91|None;Father|false|84|Stroke;Sister|true|66|None",
        "PastConditions": "Mild ankle sprain|2021|Resolved|RICE protocol",
        "CurrentConditions": "",
        "Surgeries": "Wisdom teeth extraction|1976|Standard",
        "Allergies": "",
        "Medications": "Multivitamin|1 tab|2017|General wellness",
    },
    {
        "Name": "Donna Watson",          "age": 72, "ZIP": "10010",
        "Email": "ajohnsm2020@gmail.com", "Phone": "+15551110010",
        "Conditions": "Hypothyroidism",  "PCPID": "P1010",
        "LifestyleNotes": "Pilates twice weekly; Mediterranean diet.",
        "FamilyHistory": "Mother|true|93|Hypothyroidism;Father|false|86|Heart Disease;Sister|true|70|Hypothyroidism",
        "PastConditions": "Iron deficiency anemia|2016|Resolved|Iron supplementation",
        "CurrentConditions": "Hypothyroidism|2008|Stable on levothyroxine",
        "Surgeries": "Cataract removal (left eye)|2023|Lens implant successful",
        "Allergies": "Codeine|Mild|Nausea",
        "Medications": "Levothyroxine|100mcg|2008|Hypothyroidism;Vitamin D3|2000 IU|2018|Bone health",
    },
]

rows = []
for i, m in enumerate(members):
    # Stagger COL date 6-30 months back (still inside 120-mo lookback)
    col_date = recent(180 + i * 60)
    # Stagger AAP date 1-9 months back (inside 12-mo lookback)
    aap_date = recent(30 + i * 25)
    rows.append({
        "Name": m["Name"],
        "DOB": dob_for_age(m["age"]),
        "Gender": "F",
        "Email": m["Email"],
        "Phone": m["Phone"],
        "PCPID": m["PCPID"],
        "PlanID": "PLAN-001",
        "ZIP": m["ZIP"],
        "ChronicConditions": m["Conditions"],
        "InsuranceType": "Commercial",
        "EnrollmentStart": "2026-01-01",
        "EnrollmentEnd": "2026-12-31",
        "PriorScreenings": f"COL:{col_date};AAP:{aap_date}",
        "HeightCm": 160 + (i % 4) * 3,
        "WeightKg": 60 + (i % 5) * 4,
        "SmokingStatus": "Never",
        "AlcoholUse": "None" if i % 2 == 0 else "Occasional",
        "ExerciseFrequency": "2-3x/week",
        "DietType": "Balanced",
        "SleepHoursAvg": 7,
        "StressLevel": "Low",
        "LifestyleNotes":     m.get("LifestyleNotes", ""),
        "FamilyHistory":      m.get("FamilyHistory", ""),
        "PastConditions":     m.get("PastConditions", ""),
        "CurrentConditions":  m.get("CurrentConditions", ""),
        "Surgeries":          m.get("Surgeries", ""),
        "Allergies":          m.get("Allergies", ""),
        "Medications":        m.get("Medications", ""),
        "Immunizations":      f"Influenza|{TODAY.year - 1};Tdap|{TODAY.year - 5};Pneumococcal|{TODAY.year - 3};Shingles|{TODAY.year - 2}",
    })

df = pd.DataFrame(rows)
out_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "bulk_upload_BCS_only_test.xlsx",
)
df.to_excel(out_path, index=False, sheet_name="Members")
print(f"Generated: {out_path}")
print(f"Rows: {len(df)}")
print(f"Columns: {list(df.columns)}")
