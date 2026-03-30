"""
Main Medical Agent Application
Entry point for the medical agentic AI system
"""
import logging
import json
from typing import Dict, Any, Optional
from src.medical_agents import create_medical_agent_system
from src.neo4j_connection import get_knowledge_graph
from config.settings import settings

# Configure logging
logging.basicConfig(
    level=settings.log_level,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class MedicalAIApplication:
    """
    Main application for medical AI agent system
    Coordinates patient analysis, predictions, and recommendations
    """
    
    def __init__(self):
        """Initialize the medical AI application"""
        logger.info("Initializing Medical AI Application")
        self.kg = get_knowledge_graph()
        self.agent_system = create_medical_agent_system()
        logger.info("Medical AI Application ready")
    
    def add_patient(self, patient_id: str, name: str, age: int, 
                   gender: str, additional_info: Optional[Dict] = None) -> bool:
        """
        Add a new patient to the system
        
        Args:
            patient_id: Unique patient identifier
            name: Patient name
            age: Patient age
            gender: Patient gender
            additional_info: Additional patient information
            
        Returns:
            Success status
        """
        try:
            success = self.kg.create_patient(patient_id, name, age, gender)
            if success:
                logger.info(f"Added patient: {patient_id}")
            return success
        except Exception as e:
            logger.error(f"Failed to add patient: {str(e)}")
            return False
    
    def add_patient_condition(self, patient_id: str, condition_id: str,
                            diagnosed_date: str, status: str) -> bool:
        """
        Add a medical condition to a patient
        
        Args:
            patient_id: Patient ID
            condition_id: Condition ID
            diagnosed_date: Date of diagnosis
            status: Current status (active, resolved, etc.)
            
        Returns:
            Success status
        """
        try:
            success = self.kg.relate_patient_to_condition(
                patient_id, condition_id, diagnosed_date, status
            )
            if success:
                logger.info(f"Added condition {condition_id} to patient {patient_id}")
            return success
        except Exception as e:
            logger.error(f"Failed to add patient condition: {str(e)}")
            return False
    
    def analyze_patient(self, patient_id: str) -> Dict[str, Any]:
        """
        Perform comprehensive analysis of a patient
        
        Args:
            patient_id: Patient ID for analysis
            
        Returns:
            Analysis results from all agents
        """
        try:
            logger.info(f"Starting comprehensive analysis for patient {patient_id}")
            
            # Gather patient data
            patient_history = self.kg.get_patient_history(patient_id)
            similar_patients = self.kg.find_similar_patients(patient_id)
            
            patient_data = {
                "patient_id": patient_id,
                "medical_history": patient_history,
                "similar_patients": similar_patients
            }
            
            # Run analysis through agent system
            results = self.agent_system.analyze_patient(patient_data)
            
            logger.info(f"Completed analysis for patient {patient_id}")
            return results
            
        except Exception as e:
            logger.error(f"Error during patient analysis: {str(e)}")
            return {
                "patient_id": patient_id,
                "status": "error",
                "error": str(e)
            }
    
    def predict_outcomes(self, patient_id: str, 
                        timeframe_months: int = 12) -> Dict[str, Any]:
        """
        Predict future disease outcomes
        
        Args:
            patient_id: Patient ID
            timeframe_months: Prediction timeframe in months
            
        Returns:
            Outcome predictions
        """
        try:
            logger.info(f"Predicting outcomes for patient {patient_id}")
            results = self.agent_system.predict_disease_outcomes(
                patient_id, timeframe_months
            )
            return results
        except Exception as e:
            logger.error(f"Error during outcome prediction: {str(e)}")
            return {
                "patient_id": patient_id,
                "status": "error",
                "error": str(e)
            }
    
    def generate_care_plan(self, patient_id: str) -> Dict[str, Any]:
        """
        Generate comprehensive care and prevention plan
        
        Args:
            patient_id: Patient ID
            
        Returns:
            Care plan recommendations
        """
        try:
            logger.info(f"Generating care plan for patient {patient_id}")
            results = self.agent_system.generate_prevention_plan(patient_id)
            return results
        except Exception as e:
            logger.error(f"Error during care plan generation: {str(e)}")
            return {
                "patient_id": patient_id,
                "status": "error",
                "error": str(e)
            }
    
    def get_patient_summary(self, patient_id: str) -> Dict[str, Any]:
        """
        Get summary of patient's medical profile
        
        Args:
            patient_id: Patient ID
            
        Returns:
            Patient summary with history and similar cases
        """
        try:
            history = self.kg.get_patient_history(patient_id)
            similar = self.kg.find_similar_patients(patient_id)
            
            return {
                "patient_id": patient_id,
                "medical_history": history,
                "similar_patients": similar,
                "status": "success"
            }
        except Exception as e:
            logger.error(f"Error retrieving patient summary: {str(e)}")
            return {
                "patient_id": patient_id,
                "status": "error",
                "error": str(e)
            }
    
    def custom_query(self, patient_id: str, query: str) -> Dict[str, Any]:
        """
        Test SelectorGroupChat with custom queries.
        Shows which agents are selected based on the query.
        
        Args:
            patient_id: Patient ID
            query: Custom query to send to agents
            
        Returns:
            Agent responses showing which agents were selected
        """
        try:
            logger.info(f"Processing custom query for patient {patient_id}: {query}")
            
            # Gather patient data
            patient_history = self.kg.get_patient_history(patient_id)
            similar_patients = self.kg.find_similar_patients(patient_id)
            medications = self.kg.get_patient_medications(patient_id)
            risk_profile = self.kg.get_patient_risk_profile(patient_id)
            
            patient_data = {
                "patient_id": patient_id,
                "medical_history": patient_history,
                "medications": medications,
                "risk_profile": risk_profile,
                "similar_patients": similar_patients
            }
            
            # Run custom query through agent system
            results = self.agent_system.custom_query(patient_data, query)
            
            logger.info(f"Completed custom query for patient {patient_id}")
            return results
            
        except Exception as e:
            logger.error(f"Error during custom query: {str(e)}")
            return {
                "patient_id": patient_id,
                "status": "error",
                "error": str(e)
            }
    
    def export_analysis(self, patient_id: str, filepath: str) -> bool:
        """
        Export patient analysis to JSON file
        
        Args:
            patient_id: Patient ID
            filepath: Output file path
            
        Returns:
            Success status
        """
        try:
            summary = self.get_patient_summary(patient_id)
            analysis = self.analyze_patient(patient_id)
            
            export_data = {
                "patient_id": patient_id,
                "summary": summary,
                "analysis": analysis
            }
            
            with open(filepath, 'w') as f:
                json.dump(export_data, f, indent=2)
            
            logger.info(f"Exported analysis to {filepath}")
            return True
        except Exception as e:
            logger.error(f"Failed to export analysis: {str(e)}")
            return False
    
    def close(self):
        """Clean up resources"""
        if self.kg:
            self.kg.close()
        logger.info("Application closed")


def create_app() -> MedicalAIApplication:
    """Factory function to create the application"""
    return MedicalAIApplication()


if __name__ == "__main__":
    # Example usage
    app = create_app()
    
    try:
        # Add a sample patient
        app.add_patient("P001", "John Doe", 55, "M")
        
        # Add medical conditions
        app.add_patient_condition("P001", "COND001", "2023-01-15", "active")
        app.add_patient_condition("P001", "COND002", "2022-06-20", "active")
        
        # Get patient summary
        summary = app.get_patient_summary("P001")
        print("Patient Summary:")
        print(json.dumps(summary, indent=2))
        
        # Analyze patient
        print("\nAnalyzing patient...")
        analysis = app.analyze_patient("P001")
        print("Analysis Results:")
        print(json.dumps(analysis, indent=2))
        
        # Predict outcomes
        print("\nPredicting outcomes...")
        outcomes = app.predict_outcomes("P001", 12)
        print("Outcome Predictions:")
        print(json.dumps(outcomes, indent=2))
        
        # Generate care plan
        print("\nGenerating care plan...")
        care_plan = app.generate_care_plan("P001")
        print("Care Plan:")
        print(json.dumps(care_plan, indent=2))
        
    finally:
        app.close()
