"""
Utility functions for medical AI system
"""
import json
from datetime import datetime
from typing import Dict, List, Any, Optional
import logging

logger = logging.getLogger(__name__)


class MedicalDataParser:
    """Parse and validate medical data"""
    
    @staticmethod
    def parse_patient_data(data: Dict) -> Optional[Dict]:
        """Parse and validate patient data"""
        try:
            required_fields = ['patient_id', 'name', 'age', 'gender']
            if not all(field in data for field in required_fields):
                raise ValueError(f"Missing required fields: {required_fields}")
            
            return {
                'patient_id': str(data['patient_id']),
                'name': str(data['name']),
                'age': int(data['age']),
                'gender': str(data['gender']).upper()
            }
        except Exception as e:
            logger.error(f"Error parsing patient data: {str(e)}")
            return None
    
    @staticmethod
    def parse_condition_data(data: Dict) -> Optional[Dict]:
        """Parse and validate condition data"""
        try:
            required_fields = ['condition_id', 'diagnosed_date', 'status']
            if not all(field in data for field in required_fields):
                raise ValueError(f"Missing required fields: {required_fields}")
            
            return {
                'condition_id': str(data['condition_id']),
                'diagnosed_date': str(data['diagnosed_date']),
                'status': str(data['status']).lower()
            }
        except Exception as e:
            logger.error(f"Error parsing condition data: {str(e)}")
            return None


class ReportGenerator:
    """Generate medical reports from analysis data"""
    
    @staticmethod
    def generate_patient_report(analysis: Dict) -> str:
        """Generate formatted patient report"""
        report = f"""
        ========================================
        MEDICAL ANALYSIS REPORT
        ========================================
        
        Patient ID: {analysis.get('patient_id', 'N/A')}
        Generated: {datetime.now().isoformat()}
        
        STATUS: {analysis.get('status', 'N/A')}
        
        ========================================
        ANALYSIS RESULTS
        ========================================
        
        {json.dumps(analysis, indent=2)}
        
        ========================================
        """
        return report
    
    @staticmethod
    def generate_summary_report(summary: Dict) -> str:
        """Generate formatted summary report"""
        report = f"""
        ========================================
        PATIENT SUMMARY REPORT
        ========================================
        
        Patient ID: {summary.get('patient_id', 'N/A')}
        Generated: {datetime.now().isoformat()}
        
        Medical History:
        {json.dumps(summary.get('medical_history', []), indent=2)}
        
        Similar Patients:
        {json.dumps(summary.get('similar_patients', []), indent=2)}
        
        ========================================
        """
        return report


class MetricsCalculator:
    """Calculate important medical metrics"""
    
    @staticmethod
    def calculate_risk_score(conditions: List[Dict], age: int) -> float:
        """Calculate overall risk score (0-100)"""
        base_score = 0
        
        # Age-based risk
        if age > 65:
            base_score += 20
        elif age > 50:
            base_score += 10
        
        # Condition severity-based risk
        severity_scores = {
            'Critical': 25,
            'High': 15,
            'Medium': 10,
            'Low': 5
        }
        
        for condition in conditions:
            severity = condition.get('severity', 'Low')
            base_score += severity_scores.get(severity, 5)
        
        return min(base_score, 100)
    
    @staticmethod
    def calculate_comorbidity_index(conditions: List[str]) -> int:
        """Calculate comorbidity index"""
        return len(conditions)


class AnalysisCache:
    """Cache analysis results for performance"""
    
    def __init__(self):
        self._cache = {}
    
    def get(self, key: str) -> Optional[Dict]:
        """Get cached analysis"""
        return self._cache.get(key)
    
    def set(self, key: str, value: Dict) -> None:
        """Cache analysis result"""
        self._cache[key] = {
            'data': value,
            'timestamp': datetime.now().isoformat()
        }
    
    def clear(self) -> None:
        """Clear cache"""
        self._cache.clear()
    
    def invalidate(self, key: str) -> None:
        """Invalidate specific cache entry"""
        if key in self._cache:
            del self._cache[key]


def format_medical_data(data: Any) -> str:
    """Format medical data for display"""
    if isinstance(data, dict):
        return json.dumps(data, indent=2)
    elif isinstance(data, list):
        return '\n'.join(str(item) for item in data)
    else:
        return str(data)


def validate_date_format(date_str: str) -> bool:
    """Validate date format (YYYY-MM-DD)"""
    try:
        datetime.strptime(date_str, '%Y-%m-%d')
        return True
    except ValueError:
        return False
