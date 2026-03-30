# Medical Agentic AI System with Neo4j Knowledge Graph

A sophisticated AI system for medical diagnosis, patient history analysis, future consequence prediction, and prevention strategies using **AutoGen** multi-agent framework and **Neo4j Aura** knowledge graph database.

## 🏥 Features

### Core Capabilities

- **Patient Diagnosis Prediction**: Analyze symptoms and identify potential medical conditions
- **Medical History Analysis**: Review and track disease progression patterns
- **Future Consequence Prediction**: Predict potential complications and disease trajectories
- **Prevention & Treatment Recommendations**: Generate evidence-based care plans
- **Hospital Operations Coordination**: Manage patient care pathways and referrals
- **Similar Patient Identification**: Find comparable cases from knowledge graph

### Technology Stack

- **AutoGen**: Multi-agent AI orchestration framework
- **Neo4j Aura**: Cloud-based knowledge graph database
- **OpenAI GPT**: Large language model for agent intelligence
- **Flask**: REST API for system integration
- **Python 3.8+**: Core language

## 📋 Project Structure

```
knowledge-graph-AIAgents/
├── src/
│   ├── neo4j_connection.py      # Database connection and utilities
│   ├── kg_schema.py             # Knowledge graph schema and data
│   ├── medical_agents.py        # AutoGen agents definition
│   ├── init_knowledge_graph.py  # Data initialization
│   ├── main.py                  # Main application logic
│   └── api.py                   # REST API endpoints
├── config/
│   └── settings.py              # Configuration management
├── data/                        # Data storage and exports
├── notebooks/                   # Jupyter notebooks for analysis
├── requirements.txt             # Python dependencies
├── .env.example                 # Environment configuration template
└── README.md                    # This file
```

## 🚀 Quick Start

### 1. Prerequisites

- Python 3.8 or higher
- Neo4j Aura account (free tier available at [neo4j.com](https://neo4j.com/cloud/aura/))
- OpenAI API key
- Git

### 2. Installation

```bash
# Clone repository
git clone <repository-url>
cd knowledge-graph-AIAgents

# Create virtual environment
python -m venv venv

# Activate virtual environment
# On Windows:
venv\Scripts\activate
# On macOS/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Configuration

Create `.env` file from template:

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```env
# Neo4j Aura Configuration
NEO4J_URI=neo4j+s://your-instance-id.neo4j.io
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your-secure-password

# OpenAI Configuration
OPENAI_API_KEY=sk-your-api-key
OPENAI_MODEL=gpt-4

# Application Configuration
DEBUG=False
LOG_LEVEL=INFO
```

### 4. Initialize Knowledge Graph

```bash
python -m src.init_knowledge_graph
```

This creates:

- Database constraints and indexes
- Medical conditions, symptoms, medications
- Risk factors and prevention strategies
- Sample relationships for analysis

### 5. Run Application

#### Option A: Use Main Application

```bash
python -m src.main
```

#### Option B: Use REST API

```bash
python -m src.api
```

API will be available at `http://localhost:5000`

## 📡 REST API Endpoints

### Health Check

```
GET /api/v1/health
```

### Patient Management

#### Add Patient

```
POST /api/v1/patients
Content-Type: application/json

{
    "patient_id": "P001",
    "name": "John Doe",
    "age": 55,
    "gender": "M"
}
```

#### Add Medical Condition

```
POST /api/v1/patients/<patient_id>/conditions
Content-Type: application/json

{
    "condition_id": "COND001",
    "diagnosed_date": "2023-01-15",
    "status": "active"
}
```

#### Get Patient Summary

```
GET /api/v1/patients/<patient_id>/summary
```

Response includes medical history and similar patients

### Analysis & Predictions

#### Comprehensive Patient Analysis

```
POST /api/v1/patients/<patient_id>/analysis
```

Runs all agents for:

- Medical diagnosis
- History analysis
- Consequence prediction
- Treatment recommendations
- Hospital coordination

#### Predict Future Outcomes

```
POST /api/v1/patients/<patient_id>/predict-outcomes
Content-Type: application/json

{
    "timeframe_months": 12
}
```

#### Generate Care Plan

```
GET /api/v1/patients/<patient_id>/care-plan
```

Returns comprehensive prevention and treatment plan

#### Export Analysis

```
GET /api/v1/patients/<patient_id>/export?filepath=output/patient_analysis.json
```

## 🤖 AI Agents

### 1. **Diagnostician Agent**

- Analyzes symptoms and medical history
- Identifies potential diseases and conditions
- Provides differential diagnoses with confidence levels
- Recommends diagnostic tests
- Assesses risk levels

### 2. **History Analyzer Agent**

- Reviews complete medical history
- Identifies disease progression patterns
- Tracks medication compliance and efficacy
- Analyzes vital signs and lab result trends
- Provides historical context

### 3. **Consequence Predictor Agent**

- Predicts potential complications
- Assesses disease progression scenarios
- Estimates timelines for complications
- Evaluates untreated condition impacts
- Considers demographics and lifestyle factors

### 4. **Prevention & Treatment Advisor**

- Recommends preventive measures
- Suggests lifestyle modifications
- Provides evidence-based treatment options
- Creates medication management strategies
- Develops patient education content

### 5. **Hospital Coordinator Agent**

- Coordinates patient care pathways
- Manages specialist referrals
- Allocates resources efficiently
- Tracks treatment compliance
- Documents clinical decisions

## 📊 Knowledge Graph Schema

### Node Types

- **Patient**: Individual patient records
- **Condition**: Medical conditions/diseases
- **Medication**: Pharmaceutical treatments
- **Symptom**: Clinical symptoms
- **LabTest**: Diagnostic tests and results
- **Treatment**: Medical procedures and therapies
- **RiskFactor**: Health risk factors
- **Prevention**: Preventive interventions

### Relationships

- `HAS_CONDITION`: Patient has medical condition
- `HAS_SYMPTOM`: Condition presents with symptom
- `TAKES_MEDICATION`: Patient takes medication
- `UNDERWENT_TEST`: Patient underwent lab test
- `TREATS`: Medication treats condition
- `HAS_RISK_FACTOR`: Patient has risk factor
- `PREVENTED_BY`: Condition prevented by intervention
- `CAUSES_SIDE_EFFECT`: Medication causes side effect

## 🔄 Example Workflow

```python
from src.main import create_app

# Initialize application
app = create_app()

# Add patient
app.add_patient("P001", "John Doe", 55, "M")

# Add medical conditions
app.add_patient_condition("P001", "COND001", "2023-01-15", "active")
app.add_patient_condition("P001", "COND002", "2022-06-20", "active")

# Get patient summary
summary = app.get_patient_summary("P001")

# Analyze patient
analysis = app.analyze_patient("P001")

# Predict outcomes
predictions = app.predict_outcomes("P001", 12)

# Generate care plan
care_plan = app.generate_care_plan("P001")

# Export analysis
app.export_analysis("P001", "output/patient_analysis.json")

app.close()
```

## 📈 Query Examples

### Get Patient Disease Timeline

```cypher
MATCH (p:Patient {patient_id: "P001"})-[r:HAS_CONDITION]->(c:Condition)
RETURN c.name, r.diagnosed_date, r.status, c.severity
ORDER BY r.diagnosed_date ASC
```

### Find Similar Patients

```cypher
MATCH (p1:Patient {patient_id: "P001"})-[:HAS_CONDITION]->(c:Condition)
MATCH (p2:Patient)-[:HAS_CONDITION]->(c:Condition)
WHERE p2.patient_id <> p1.patient_id
RETURN p2.patient_id, p2.name, count(c) as shared_conditions
ORDER BY shared_conditions DESC
LIMIT 5
```

### Get Condition Complications

```cypher
MATCH (c1:Condition {condition_id: "COND001"})-[r:COMPOUNDS]->(c2:Condition)
RETURN c2.name, c2.severity, c2.description
```

## 🔐 Security Considerations

- Use environment variables for all credentials
- Enable Neo4j Aura encryption (default enabled)
- Implement role-based access control in Neo4j
- Secure API endpoints with authentication tokens
- Comply with HIPAA and data protection regulations
- Regular security audits and updates

## ⚙️ Configuration Options

### Environment Variables

- `NEO4J_URI`: Neo4j Aura connection URI
- `NEO4J_USERNAME`: Database username
- `NEO4J_PASSWORD`: Database password
- `NEO4J_DATABASE`: Database name (default: "neo4j")
- `OPENAI_API_KEY`: OpenAI API key
- `OPENAI_MODEL`: LLM model (default: "gpt-4")
- `DEBUG`: Enable debug mode (default: False)
- `LOG_LEVEL`: Logging level (DEBUG, INFO, WARNING, ERROR)

## 📚 Additional Resources

- [Neo4j Documentation](https://neo4j.com/docs/)
- [AutoGen Documentation](https://microsoft.github.io/autogen/)
- [OpenAI API Reference](https://platform.openai.com/docs/)
- [Cypher Query Language](https://neo4j.com/docs/cypher-manual/current/)

## 🤝 Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## 📝 License

This project is licensed under the MIT License - see LICENSE file for details.

## ⚠️ Disclaimer

This system is designed for educational and research purposes. For actual medical applications, ensure:

- Compliance with healthcare regulations (HIPAA, GDPR, etc.)
- Proper clinical validation and testing
- Integration with licensed healthcare systems
- Appropriate human oversight and approval
- Proper documentation and auditability

## 🆘 Support & Troubleshooting

### Neo4j Connection Issues

- Verify NEO4J_URI is correct
- Check firewall settings allow access
- Confirm credentials are valid
- Test connection: `python -c "from src.neo4j_connection import get_knowledge_graph; kg = get_knowledge_graph()"`

### OpenAI API Issues

- Verify API key is valid
- Check rate limits
- Ensure sufficient credits
- Test with simple query first

### Agent Communication Issues

- Check OpenAI model availability
- Verify agent configuration
- Review logs for error details
- Ensure sufficient timeout settings

## 📧 Contact

For questions or support, please open an issue or contact the development team.

---

**Last Updated**: March 2026
**Version**: 1.0.0
