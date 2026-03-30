"""
Medical AI Agents using AutoGen 0.7.5 SelectorGroupChat
7 specialized agents - LLM dynamically selects the right agent per query
"""
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.teams import SelectorGroupChat
from autogen_agentchat.conditions import MaxMessageTermination, TextMentionTermination
from autogen_ext.models.openai import AzureOpenAIChatCompletionClient
from typing import Any, Dict
import logging
import asyncio
from src.neo4j_connection import get_knowledge_graph
from config.settings import settings

logger = logging.getLogger(__name__)


class MedicalAgentSystem:
    """
    Multi-agent system using SelectorGroupChat.
    The LLM decides which agent should respond based on the conversation context.
    """

    def __init__(self):
        self.kg = get_knowledge_graph()
        self.model_client = AzureOpenAIChatCompletionClient(
            azure_deployment=settings.openai_model,
            azure_endpoint=settings.endpoint,
            api_key=settings.openai_api_key,
            api_version=settings.azure_openai_api_version,
            model=settings.openai_model,
        )
        self._initialize_agents()

    def _initialize_agents(self):
        self.diagnostician = AssistantAgent(
            name="diagnostician",
            system_message="""You are an expert Medical Diagnostician Agent. Your role is to:
1. Analyze patient symptoms and medical history from the knowledge graph
2. Identify potential diseases or conditions
3. Consider comorbidities and risk factors
4. Provide differential diagnoses with confidence levels
5. Recommend further diagnostic tests if needed

Format your diagnosis as:
- Primary Diagnosis: [condition name] (Confidence: X%)
- Differential Diagnoses: [list with probabilities]
- Contributing Factors: [list]
- Recommended Tests: [list]
- Risk Assessment: [high/medium/low]
- Next Steps: [immediate actions]""",
            model_client=self.model_client,
        )

        self.history_analyzer = AssistantAgent(
            name="history_analyzer",
            system_message="""You are an expert Medical History Analyzer. Your role is to:
1. Review complete patient medical history from the knowledge graph
2. Identify disease progression patterns and trends
3. Assess medication compliance and efficacy
4. Identify trends in vital signs and lab results
5. Provide historical context for current conditions
6. Detect patterns that may indicate deterioration

Format your analysis as:
- Disease Timeline: [chronological progression]
- Medication History: [current and past medications]
- Lab Result Trends: [analysis of trends]
- Previous Treatments: [list with outcomes]
- Historical Risk Indicators: [emerging patterns]
- Progression Risk: [likelihood of worsening]""",
            model_client=self.model_client,
        )

        self.consequence_predictor = AssistantAgent(
            name="consequence_predictor",
            system_message="""You are an expert Medical Consequence Predictor. Your role is to:
1. Predict potential complications of current conditions
2. Assess disease progression scenarios
3. Estimate timeline for potential complications
4. Evaluate impact of untreated conditions
5. Consider patient demographics and lifestyle
6. Provide prognosis estimates

Format your predictions as:
- Likely Complications: [list with probability percentages]
- Progression Timeline: [estimated months/years]
- Organ/System Risk: [affected areas and severity]
- Quality of Life Impact: [mild/moderate/severe]
- Critical Intervention Points: [timeline with actions]
- 5-10 Year Prognosis: [detailed scenario analysis]
- Mortality Risk: [percentage estimate]""",
            model_client=self.model_client,
        )

        self.prevention_advisor = AssistantAgent(
            name="prevention_advisor",
            system_message="""You are an expert Prevention and Treatment Advisor. Your role is to:
1. Recommend preventive measures for identified risks
2. Suggest evidence-based lifestyle modifications
3. Recommend evidence-based treatments and medications
4. Provide medication management strategies
5. Create actionable patient education plans
6. Optimize current treatment regimens

Format your recommendations as:
- Immediate Actions (Next 1 week): [specific interventions]
- Short-term Plan (1-3 months): [specific interventions]
- Long-term Prevention (6-12 months): [lifestyle changes]
- Medication Optimizations: [adjustments/alternatives]
- Monitoring Plan: [frequency and metrics]
- Patient Education: [key points to communicate]
- Lifestyle Modifications: [diet, exercise, stress management]""",
            model_client=self.model_client,
        )

        self.hospital_coordinator = AssistantAgent(
            name="hospital_coordinator",
            system_message="""You are a Hospital Operations Coordinator. Your role is to:
1. Coordinate patient care pathways and workflows
2. Ensure timely referrals and specialist scheduling
3. Manage resource allocation and bed management
4. Track compliance with treatment plans
5. Document clinical decisions and outcomes
6. Optimize hospital resource utilization

Format your coordination plan as:
- Care Pathway: [step-by-step clinical pathway]
- Required Resources: [staff, equipment, tests needed]
- Referral Recommendations: [specialists and timing]
- Scheduling: [appointment priorities and timing]
- Follow-up Plan: [timeline and responsibilities]
- Resource Allocation: [bed, equipment, staff needs]
- Discharge Planning: [post-hospital care]""",
            model_client=self.model_client,
        )

        self.lab_specialist = AssistantAgent(
            name="lab_specialist",
            system_message="""You are a Laboratory & Diagnostic Test Specialist. Your role is to:
1. Recommend appropriate diagnostic tests based on symptoms
2. Interpret lab results in clinical context
3. Identify abnormal values and their significance
4. Recommend follow-up testing if needed
5. Correlate lab findings with clinical presentation
6. Suggest optimal testing sequences

Format your recommendations as:
- Recommended Tests: [list with priority]
- Test Rationale: [why each test is needed]
- Expected Results: [normal ranges and what to look for]
- Interpretation Guide: [what results mean]
- Follow-up Testing: [if initial results are abnormal]
- Timeline: [when to perform tests]
- Cost-Benefit Analysis: [necessity vs. cost]""",
            model_client=self.model_client,
        )

        self.education_officer = AssistantAgent(
            name="education_officer",
            system_message="""You are a Patient Education & Compliance Officer. Your role is to:
1. Create personalized patient education materials
2. Explain medical conditions in simple terms
3. Provide medication adherence strategies
4. Develop lifestyle modification plans
5. Create follow-up reminders and schedules
6. Assess patient understanding and barriers

Format your education plan as:
- Condition Explanation: [simple, understandable description]
- Medication Guide: [how to take, side effects, interactions]
- Lifestyle Changes: [specific, achievable modifications]
- Warning Signs: [when to seek immediate care]
- Adherence Strategies: [reminders, support systems]
- Follow-up Schedule: [appointments and tests]
- Support Resources: [support groups, hotlines, websites]
- Barriers Assessment: [potential obstacles and solutions]""",
            model_client=self.model_client,
        )

    def _build_patient_context(self, patient_id: str) -> Dict[str, Any]:
        return {
            "history": self.kg.get_patient_history(patient_id),
            "medications": self.kg.get_patient_medications(patient_id),
            "risk_profile": self.kg.get_patient_risk_profile(patient_id),
            "similar_patients": self.kg.find_similar_patients(patient_id),
        }

    def _create_selector_team(self) -> SelectorGroupChat:
        """Create a SelectorGroupChat — LLM picks the best agent per turn."""
        return SelectorGroupChat(
            participants=[
                self.diagnostician,
                self.history_analyzer,
                self.consequence_predictor,
                self.prevention_advisor,
                self.hospital_coordinator,
                self.lab_specialist,
                self.education_officer,
            ],
            model_client=self.model_client,
            termination_condition=MaxMessageTermination(max_messages=15),
            selector_prompt="""You are coordinating a medical team. Based on the conversation so far,
select the MOST appropriate next agent to respond. Consider:
- diagnostician: for diagnosis, symptoms analysis, differential diagnosis
- history_analyzer: for medical history review, disease progression, trends
- consequence_predictor: for predicting complications, prognosis, outcomes
- prevention_advisor: for treatment plans, prevention, lifestyle changes, medications
- hospital_coordinator: for care coordination, referrals, scheduling, resources
- lab_specialist: for lab tests, diagnostic tests, test interpretation
- education_officer: for patient education, compliance, simple explanations

Select the agent whose expertise best matches what's needed next.
Do NOT select an agent that has already provided their analysis unless new information requires it.""",
        )

    def _run_async(self, coro):
        """Run async coroutine from sync context."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, coro)
                    return future.result()
            else:
                return loop.run_until_complete(coro)
        except RuntimeError:
            return asyncio.run(coro)

    async def _run_team(self, task: str) -> Dict[str, Any]:
        """Run the selector group chat with a task."""
        team = self._create_selector_team()
        result = await team.run(task=task)

        agent_responses = {}
        for msg in result.messages:
            if hasattr(msg, "source") and msg.source != "user":
                agent_responses[msg.source] = msg.content

        return agent_responses

    def analyze_patient(self, patient_data: Dict[str, Any]) -> Dict[str, Any]:
        patient_id = patient_data.get("patient_id")
        try:
            ctx = self._build_patient_context(patient_id)
            task = f"""Perform comprehensive medical analysis for patient {patient_id}:

PATIENT DATA: {patient_data}
MEDICAL HISTORY: {ctx['history']}
CURRENT MEDICATIONS: {ctx['medications']}
RISK PROFILE: {ctx['risk_profile']}
SIMILAR CASES: {ctx['similar_patients']}

Each specialist should provide their analysis. Cover diagnosis, history review,
consequence prediction, prevention plan, hospital coordination, lab recommendations,
and patient education."""

            responses = self._run_async(self._run_team(task))
            return {
                "patient_id": patient_id,
                "status": "completed",
                "analysis": responses,
            }
        except Exception as e:
            logger.error(f"Error analyzing patient {patient_id}: {str(e)}")
            return {"patient_id": patient_id, "status": "error", "error": str(e)}

    def predict_disease_outcomes(self, patient_id: str, timeframe_months: int = 12) -> Dict[str, Any]:
        try:
            ctx = self._build_patient_context(patient_id)
            task = f"""Predict disease trajectory for patient {patient_id} over {timeframe_months} months:

MEDICAL HISTORY: {ctx['history']}
RISK PROFILE: {ctx['risk_profile']}

Provide: likely outcomes, worst/best case scenarios, critical intervention windows,
survival probability, quality of life projections."""

            responses = self._run_async(self._run_team(task))
            return {
                "patient_id": patient_id,
                "timeframe_months": timeframe_months,
                "status": "completed",
                "prediction": responses,
            }
        except Exception as e:
            logger.error(f"Error predicting outcomes: {str(e)}")
            return {"patient_id": patient_id, "status": "error", "error": str(e)}

    def generate_prevention_plan(self, patient_id: str) -> Dict[str, Any]:
        try:
            ctx = self._build_patient_context(patient_id)
            task = f"""Create comprehensive care and prevention plan for patient {patient_id}:

MEDICAL HISTORY: {ctx['history']}
CURRENT MEDICATIONS: {ctx['medications']}
SIMILAR CASES: {ctx['similar_patients']}

Include: immediate interventions, short/long-term strategies, lifestyle modifications,
medication optimization, monitoring schedule, patient education, specialist referrals."""

            responses = self._run_async(self._run_team(task))
            return {
                "patient_id": patient_id,
                "status": "completed",
                "plan": responses,
            }
        except Exception as e:
            logger.error(f"Error generating care plan: {str(e)}")
            return {"patient_id": patient_id, "status": "error", "error": str(e)}


def create_medical_agent_system() -> MedicalAgentSystem:
    return MedicalAgentSystem()
