from fastapi import FastAPI, HTTPException, Query
from neo4j_loader import load_to_neo4j
from synthetic_data import DISEASES
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Care Gap Knowledge Graph API")


@app.get("/diseases")
def get_all_diseases():
    return [{"name": d["name"], "category": d["category"]} for d in DISEASES]


@app.get("/diseases/{name}")
def get_disease(name: str):
    disease = next((d for d in DISEASES if d["name"].lower() == name.lower()), None)
    if not disease:
        raise HTTPException(status_code=404, detail=f"Disease '{name}' not found")
    return disease


@app.get("/diseases/{name}/care-gaps")
def get_care_gaps(name: str):
    disease = next((d for d in DISEASES if d["name"].lower() == name.lower()), None)
    if not disease:
        raise HTTPException(status_code=404, detail=f"Disease '{name}' not found")
    return {"disease": disease["name"], "care_gaps": disease["care_gaps"]}


@app.get("/diseases/{name}/symptoms")
def get_symptoms(name: str):
    disease = next((d for d in DISEASES if d["name"].lower() == name.lower()), None)
    if not disease:
        raise HTTPException(status_code=404, detail=f"Disease '{name}' not found")
    return {"disease": disease["name"], "symptoms": disease["symptoms"]}


@app.get("/diseases/{name}/treatments")
def get_treatments(name: str):
    disease = next((d for d in DISEASES if d["name"].lower() == name.lower()), None)
    if not disease:
        raise HTTPException(status_code=404, detail=f"Disease '{name}' not found")
    return {
        "disease": disease["name"],
        "treatments": disease["treatments"],
        "cures": disease["cures"]
    }


@app.get("/categories/{category}")
def get_by_category(category: str):
    results = [d for d in DISEASES if d["category"].lower() == category.lower()]
    if not results:
        raise HTTPException(status_code=404, detail=f"No diseases found for category '{category}'")
    return results


@app.post("/neo4j/load")
def load_neo4j(clear: bool = Query(default=False, description="Clear existing graph before loading")):
    try:
        result = load_to_neo4j(clear=clear)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/summary")
def summary():
    categories = {}
    for d in DISEASES:
        categories.setdefault(d["category"], []).append(d["name"])
    return {
        "total_diseases": len(DISEASES),
        "categories": categories
    }
