"""
Medical AI Agents using AutoGen
Defines specialized agents for medical diagnosis, history analysis, 
consequence prediction, and prevention advising
"""
import autogen
from typing import Any, Dict, List, Optional
import logging
from src.neo4j_connection import get_knowledge_graph
from config.settings import settings

logger = logging.getLogger(__name__)

# Configure OpenAI for AutoGen
autogen.config_list_from_json("OAI_CONFIG_LIST", file_location=".")


class MedicalAgentSystem:
    """
    Multi-agent system for medical analysis using AutoGen
    Coordinates between different specialist agents
    """
    
    def __init__(self):
        """Initialize the medical agent system"""
        self.kg = get_knowledge_graph()
        self.llm_config = {
            "config_list": autogen.config_list_from_json(
                "OAI_CONFIG_LIST",
                file_location=".",
                filter_dict={"model": settings.openai_model}
            ),
            "temperature": 0.7,
            "timeout": 120,
        }
        self._initialize_agents()
    
    def _initialize_agents(self):
        """Initialize all medical specialist agents"""
        
        # User proxy agent for interaction
        self.user_proxy = autogen.UserProxyAgent(
            name="user_proxy",
            system_message="A medical professional seeking analysis and recommendations.",
            human_input_mode="NEVER",
            max_consecutive_auto_reply=10,
            code_execution_config={
                "work_dir": "work",
                "use_docker": False,
            },
        )
        
        # Medical Diagnostician Agent - Predicts patient issues
        self.diagnostician = autogen.AssistantAgent(
            name="diagnostician",
            system_message="""You are an expert Medical Diagnostician Agent. Your role is to:
1. Analyze patient symptoms and medical history
2. Identify potential diseases or conditions
3. Consider comorbidities and risk factors
4. Provide differential diagnoses with confidence levels
5. Recommend further diagnostic tests if needed

Use the following format for diagnosis:
- Primary Diagnosis: [condition name] (Confidence: X%)
- Differential Diagnoses: [list]
- Contributing Factors: [list]
- Recommended Tests: [list]
- Risk Assessment: [high/medium/low]""",
            llm_config=self.llm_config,
        )
        
        # Medical History Analyzer Agent - Analyzes patient history
        self.history_analyzer = autogen.AssistantAgent(
            name="history_analyzer",
            system_message="""You are an expert Medical History Analyzer. Your role is to:
1. Review complete patient medical history
2. Identify disease progression patterns
3. Assess medication compliance and efficacy
4. Identify trends in vital signs and lab results
5. Provide historical context for current conditions

Use structured analysis format:
- Disease Timeline: [chronological list]
- Medication History: [current and past]
- Lab Result Trends: [analysis]
- Previous Treatments: [list with outcomes]
- Historical Risk Indicators: [list]""",
            llm_config=self.llm_config,
        )
        
        # Consequence Predictor Agent - Predicts future outcomes
        self.consequence_predictor = autogen.AssistantAgent(
            name="consequence_predictor",
            system_message="""You are an expert Medical Consequence Predictor. Your role is to:
1. Predict potential complications of current conditions
2. Assess disease progression scenarios
3. Estimate timeline for potential complications
4. Evaluate impact of untreated conditions
5. Consider patient demographics and lifestyle

Prediction format:
- Likely Complications: [list with probability]
- Progression Timeline: [estimated months/years]
- Organ/System Risk: [affected areas]
- Quality of Life Impact: [mild/moderate/severe]
- Critical Intervention Points: [timeline with actions]
- 5-10 Year Prognosis: [detailed scenario analysis]""",
            llm_config=self.llm_config,
        )
        
        # Prevention & Treatment Advisor Agent
        self.prevention_advisor = autogen.AssistantAgent(
            name="prevention_advisor",
            system_message="""You are an expert Prevention and Treatment Advisor. Your role is to:
1. Recommend preventive measures for identified risks
2. Suggest lifestyle modifications
3. Recommend evidence-based treatments
4. Provide medication management strategies
5. Create actionable patient education plans

Recommendations format:
- Immediate Actions (Next 1 week): [list]
- Short-term Plan (1-3 months): [specific interventions]
- Long-term Prevention (6-12 months): [lifestyle changes]
- Medication Optimizations: [adjustments/alternatives]
- Monitoring Plan: [frequency and metrics]
- Patient Education: [key points to communicate]""",
            llm_config=self.llm_config,
        )
        
        # Hospital Operations Coordinator Agent
        self.hospital_coordinator = autogen.AssistantAgent(
            name="hospital_coordinator",
            system_message="""You are a Hospital Operations Coordinator. Your role is to:
1. Coordinate patient care pathways
2. Ensure timely referrals and scheduling
3. Manage resource allocation
4. Track compliance with treatment plans
5. Document clinical decisions

Response format:
- Care Pathway: [step-by-step plan]
- Required Resources: [staff, equipment, tests]
- Referral Recommendations: [specialists needed]
- Scheduling: [appointment priorities]
- Follow-up Plan: [timeline and responsibilities]""",
            llm_config=self.llm_config,
        )
    
    def analyze_patient(self, patient_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Comprehensive patient analysis using all agents
        
        Args:
            patient_data: Patient information including id, symptoms, history
            
        Returns:
            Comprehensive analysis from all agents
        """
        patient_id = patient_data.get("patient_id")
        
        # Retrieve patient history from knowledge graph
        patient_history = self.kg.get_patient_history(patient_id)
        similar_patients = self.kg.find_similar_patients(patient_id)
        
        # Create analysis prompt
        analysis_prompt = f"""
        Analyze the following patient case comprehensively:
        
        Patient Data:
        {patient_data}
        
        Patient Medical History:
        {patient_history}
        
        Similar Patient Cases:
        {similar_patients}
        
        Please provide:
        1. Medical diagnosis and risk assessment
        2. Historical disease progression analysis
        3. Future consequence predictions
        4. Prevention and treatment recommendations
        5. Hospital care coordination plan
        """
        
        try:
            # Initiate group chat between agents
            group_chat = autogen.GroupChat(
                agents=[
                    self.diagnostician,
                    self.history_analyzer,
                    self.consequence_predictor,
                    self.prevention_advisor,
                    self.hospital_coordinator
                ],
                messages=[],
                max_round=8,
            )
            
            manager = autogen.GroupChatManager(
                groupchat=group_chat,
                llm_config=self.llm_config
            )
            
            # Start group chat
            self.user_proxy.initiate_chat(
                manager,
                message=analysis_prompt,
                summary_method="reflection_with_llm",
            )
            
            logger.info(f"Completed analysis for patient {patient_id}")
            
            return {
                "patient_id": patient_id,
                "status": "completed",
                "analysis": manager.groupchat.messages[-1] if manager.groupchat.messages else {},
            }
            
        except Exception as e:
            logger.error(f"Error analyzing patient {patient_id}: {str(e)}")
            return {
                "patient_id": patient_id,
                "status": "error",
                "error": str(e),
            }
    
    def predict_disease_outcomes(self, patient_id: str, 
                                  timeframe_months: int = 12) -> Dict[str, Any]:
        """
        Predict future disease outcomes for a patient
        
        Args:
            patient_id: Patient ID
            timeframe_months: Prediction timeframe in months
            
        Returns:
            Outcome predictions
        """
        patient_history = self.kg.get_patient_history(patient_id)
        
        prediction_prompt = f"""
        Based on the patient's medical history:
        {patient_history}
        
        Predict the patient's disease trajectory over the next {timeframe_months} months:
        1. Most likely outcomes
        2. Worst-case scenarios
        3. Best-case scenarios with intervention
        4. Critical intervention windows
        5. Survival/recovery probability estimates
        """
        
        try:
            self.user_proxy.initiate_chat(
                self.consequence_predictor,
                message=prediction_prompt,
            )
            
            logger.info(f"Completed outcome prediction for patient {patient_id}")
            
            return {
                "patient_id": patient_id,
                "timeframe_months": timeframe_months,
                "status": "completed"
            }
            
        except Exception as e:
            logger.error(f"Error predicting outcomes for patient {patient_id}: {str(e)}")
            return {
                "patient_id": patient_id,
                "status": "error",
                "error": str(e)
            }
    
    def generate_prevention_plan(self, patient_id: str) -> Dict[str, Any]:
        """
        Generate comprehensive prevention and intervention plan
        
        Args:
            patient_id: Patient ID
            
        Returns:
            Prevention plan with recommendations
        """
        patient_history = self.kg.get_patient_history(patient_id)
        similar_patients = self.kg.find_similar_patients(patient_id)
        
        prevention_prompt = f"""
        For patient {patient_id} with the following profile:
        
        Medical History:
        {patient_history}
        
        Comparable Patient Cases:
        {similar_patients}
        
        Create a comprehensive prevention and intervention plan including:
        1. Immediate interventions (next 1 week)
        2. Short-term strategies (1-3 months)
        3. Long-term prevention plan (6-12 months)
        4. Lifestyle modifications
        5. Medication management
        6. Regular monitoring schedule
        7. Patient education content
        """
        
        try:
            self.user_proxy.initiate_chat(
                self.prevention_advisor,
                message=prevention_prompt,
            )
            
            logger.info(f"Generated prevention plan for patient {patient_id}")
            
            return {
                "patient_id": patient_id,
                "status": "completed"
            }
            
        except Exception as e:
            logger.error(f"Error generating prevention plan for patient {patient_id}: {str(e)}")
            return {
                "patient_id": patient_id,
                "status": "error",
                "error": str(e)
            }


def create_medical_agent_system() -> MedicalAgentSystem:
    """Factory function to create medical agent system"""
    return MedicalAgentSystem()
