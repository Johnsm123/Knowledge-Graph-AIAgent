"""
REST API for Medical AI Agent System using Flask
Provides endpoints for patient management and analysis
"""
from flask import Flask, request, jsonify, Blueprint
import logging
from src.main import create_app
from typing import Dict, Any

logger = logging.getLogger(__name__)

# Create Flask app
app = Flask(__name__)
app.config['JSON_SORT_KEYS'] = False

# Initialize medical AI app
medical_app = None


def get_medical_app():
    """Get or create medical app instance"""
    global medical_app
    if medical_app is None:
        medical_app = create_app()
    return medical_app


# API Routes Blueprint
api_bp = Blueprint('api', __name__, url_prefix='/api/v1')


@api_bp.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "message": "Medical AI Agent System is running"
    }), 200


@api_bp.route('/patients', methods=['POST'])
def add_patient():
    """
    Add a new patient
    
    Request body:
    {
        "patient_id": "P001",
        "name": "John Doe",
        "age": 55,
        "gender": "M"
    }
    """
    try:
        data = request.get_json()
        required_fields = ['patient_id', 'name', 'age', 'gender']
        
        if not all(field in data for field in required_fields):
            return jsonify({
                "error": "Missing required fields",
                "required": required_fields
            }), 400
        
        app_instance = get_medical_app()
        success = app_instance.add_patient(
            patient_id=data['patient_id'],
            name=data['name'],
            age=data['age'],
            gender=data['gender']
        )
        
        if success:
            return jsonify({
                "status": "success",
                "message": f"Patient {data['patient_id']} added successfully"
            }), 201
        else:
            return jsonify({
                "status": "error",
                "message": "Failed to add patient"
            }), 500
            
    except Exception as e:
        logger.error(f"Error adding patient: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@api_bp.route('/patients/<patient_id>/conditions', methods=['POST'])
def add_patient_condition(patient_id):
    """
    Add a medical condition to patient
    
    Request body:
    {
        "condition_id": "COND001",
        "diagnosed_date": "2023-01-15",
        "status": "active"
    }
    """
    try:
        data = request.get_json()
        required_fields = ['condition_id', 'diagnosed_date', 'status']
        
        if not all(field in data for field in required_fields):
            return jsonify({
                "error": "Missing required fields",
                "required": required_fields
            }), 400
        
        app_instance = get_medical_app()
        success = app_instance.add_patient_condition(
            patient_id=patient_id,
            condition_id=data['condition_id'],
            diagnosed_date=data['diagnosed_date'],
            status=data['status']
        )
        
        if success:
            return jsonify({
                "status": "success",
                "message": f"Condition added to patient {patient_id}"
            }), 201
        else:
            return jsonify({
                "status": "error",
                "message": "Failed to add condition"
            }), 500
            
    except Exception as e:
        logger.error(f"Error adding condition: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@api_bp.route('/patients/<patient_id>/summary', methods=['GET'])
def get_patient_summary(patient_id):
    """Get patient summary with medical history"""
    try:
        app_instance = get_medical_app()
        summary = app_instance.get_patient_summary(patient_id)
        return jsonify(summary), 200
    except Exception as e:
        logger.error(f"Error retrieving summary: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@api_bp.route('/patients/<patient_id>/analysis', methods=['POST'])
def analyze_patient(patient_id):
    """
    Perform comprehensive patient analysis
    Uses all medical agents for analysis
    """
    try:
        app_instance = get_medical_app()
        analysis = app_instance.analyze_patient(patient_id)
        return jsonify(analysis), 200
    except Exception as e:
        logger.error(f"Error analyzing patient: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@api_bp.route('/patients/<patient_id>/predict-outcomes', methods=['POST'])
def predict_outcomes(patient_id):
    """
    Predict future disease outcomes
    
    Request body (optional):
    {
        "timeframe_months": 12
    }
    """
    try:
        data = request.get_json() or {}
        timeframe = data.get('timeframe_months', 12)
        
        app_instance = get_medical_app()
        predictions = app_instance.predict_outcomes(patient_id, timeframe)
        return jsonify(predictions), 200
    except Exception as e:
        logger.error(f"Error predicting outcomes: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@api_bp.route('/patients/<patient_id>/care-plan', methods=['GET'])
def get_care_plan(patient_id):
    """Generate comprehensive care and prevention plan"""
    try:
        app_instance = get_medical_app()
        care_plan = app_instance.generate_care_plan(patient_id)
        return jsonify(care_plan), 200
    except Exception as e:
        logger.error(f"Error generating care plan: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@api_bp.route('/patients/<patient_id>/export', methods=['GET'])
def export_analysis(patient_id):
    """
    Export patient analysis to JSON
    
    Query parameters:
    - filepath: Output file path (optional)
    """
    try:
        filepath = request.args.get('filepath', f'output/{patient_id}_analysis.json')
        app_instance = get_medical_app()
        success = app_instance.export_analysis(patient_id, filepath)
        
        if success:
            return jsonify({
                "status": "success",
                "message": f"Analysis exported to {filepath}"
            }), 200
        else:
            return jsonify({
                "status": "error",
                "message": "Failed to export analysis"
            }), 500
    except Exception as e:
        logger.error(f"Error exporting analysis: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


# Register blueprint
app.register_blueprint(api_bp)


@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors"""
    return jsonify({
        "status": "error",
        "message": "Endpoint not found"
    }), 404


@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors"""
    logger.error(f"Internal server error: {str(error)}")
    return jsonify({
        "status": "error",
        "message": "Internal server error"
    }), 500


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    app.run(debug=True, host='0.0.0.0', port=5000)
