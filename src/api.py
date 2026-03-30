"""
REST API for Medical AI Agent System using FastAPI
Provides endpoints for patient management and analysis
"""
from fastapi import FastAPI, APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional
import logging
from src.main import create_app

logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(title="Medical AI Agent System")

# Initialize medical AI app
medical_app = None


def get_medical_app():
    """Get or create medical app instance"""
    global medical_app
    if medical_app is None:
        medical_app = create_app()
    return medical_app


# Request models
class PatientRequest(BaseModel):
    patient_id: str
    name: str
    age: int
    gender: str


class ConditionRequest(BaseModel):
    condition_id: str
    diagnosed_date: str
    status: str


class PredictRequest(BaseModel):
    timeframe_months: Optional[int] = 12


# API Router
router = APIRouter(prefix="/api/v1")


@router.get("/health")
def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "message": "Medical AI Agent System is running"}


@router.post("/patients", status_code=201)
def add_patient(data: PatientRequest):
    """Add a new patient"""
    try:
        app_instance = get_medical_app()
        success = app_instance.add_patient(
            patient_id=data.patient_id,
            name=data.name,
            age=data.age,
            gender=data.gender
        )
        if success:
            return {"status": "success", "message": f"Patient {data.patient_id} added successfully"}
        raise HTTPException(status_code=500, detail="Failed to add patient")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding patient: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/patients/{patient_id}/conditions", status_code=201)
def add_patient_condition(patient_id: str, data: ConditionRequest):
    """Add a medical condition to patient"""
    try:
        app_instance = get_medical_app()
        success = app_instance.add_patient_condition(
            patient_id=patient_id,
            condition_id=data.condition_id,
            diagnosed_date=data.diagnosed_date,
            status=data.status
        )
        if success:
            return {"status": "success", "message": f"Condition added to patient {patient_id}"}
        raise HTTPException(status_code=500, detail="Failed to add condition")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding condition: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/patients/{patient_id}/summary")
def get_patient_summary(patient_id: str):
    """Get patient summary with medical history"""
    try:
        app_instance = get_medical_app()
        return app_instance.get_patient_summary(patient_id)
    except Exception as e:
        logger.error(f"Error retrieving summary: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/patients/{patient_id}/analysis")
def analyze_patient(patient_id: str):
    """Perform comprehensive patient analysis using all medical agents"""
    try:
        app_instance = get_medical_app()
        return app_instance.analyze_patient(patient_id)
    except Exception as e:
        logger.error(f"Error analyzing patient: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/patients/{patient_id}/predict-outcomes")
def predict_outcomes(patient_id: str, data: PredictRequest = PredictRequest()):
    """Predict future disease outcomes"""
    try:
        app_instance = get_medical_app()
        return app_instance.predict_outcomes(patient_id, data.timeframe_months)
    except Exception as e:
        logger.error(f"Error predicting outcomes: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/patients/{patient_id}/care-plan")
def get_care_plan(patient_id: str):
    """Generate comprehensive care and prevention plan"""
    try:
        app_instance = get_medical_app()
        return app_instance.generate_care_plan(patient_id)
    except Exception as e:
        logger.error(f"Error generating care plan: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/patients/{patient_id}/export")
def export_analysis(
    patient_id: str,
    filepath: str = Query(default=None)
):
    """Export patient analysis to JSON"""
    try:
        output_path = filepath or f"output/{patient_id}_analysis.json"
        app_instance = get_medical_app()
        success = app_instance.export_analysis(patient_id, output_path)
        if success:
            return {"status": "success", "message": f"Analysis exported to {output_path}"}
        raise HTTPException(status_code=500, detail="Failed to export analysis")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error exporting analysis: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# Register router
app.include_router(router)


if __name__ == "__main__":
    import uvicorn
    logging.basicConfig(level=logging.INFO)
    uvicorn.run("src.api:app", host="0.0.0.0", port=8000, reload=True)
