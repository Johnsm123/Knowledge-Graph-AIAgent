# Care Gap Management System with Neo4j Knowledge Graph

A sophisticated AI system for healthcare quality measure compliance, care gap detection, and member outreach using **AutoGen** SelectorGroupChat multi-agent framework and **Neo4j Aura** knowledge graph database.

## 🏥 Features

### Core Capabilities

- **Care Gap Detection**: Identify members non-compliant with HEDIS quality measures (BCS, COL, CCS, HbA1c)
- **Golden Reference Validation**: Cross-check member claims against authoritative CPT code lists and lookback periods
- **Automated Gap Analysis**: System-level CPT code matching with lookback window validation
- **AI-Powered Outreach Planning**: Generate prioritised care manager talking points and outreach strategies
- **Benefit Coverage Verification**: Confirm plan coverage and member cost for required services
- **Dynamic Agent Orchestration**: LLM-driven SelectorGroupChat decides which agent responds based on conversation context

### Technology Stack

- **AutoGen 0.7.5**: SelectorGroupChat multi-agent orchestration framework
- **Neo4j Aura**: Cloud-based knowledge graph database with MERGE-based idempotent operations
- **Azure OpenAI GPT-5**: Large language model for agent intelligence
- **Flask**: REST API for system integration
- **Python 3.8+**: Core language
- **Pandas**: Excel data loading and transformation

## 📋 Project Structure

```
Knowledge-Graph-AIAgent/
├── config/
│   ├── __init__.py
│   └── settings.py                      # Configuration management (reads .env)
├── src/
│   ├── __init__.py
│   ├── neo4j_connection.py              # Core Neo4j Bolt driver
│   ├── care_gap_neo4j.py                # MERGE-based Neo4j operations + query helpers
│   ├── care_gap_data_loader.py          # Excel → Neo4j loader with golden reference
│   ├── care_gap_agents.py               # 3 care gap agents (SelectorGroupChat)
│   ├── care_gap_api.py                  # REST API endpoints
│   ├── wipe_and_reload.py               # Database reset + fresh reload utility
│   ├── test_agents.py                   # Agent testing on real Neo4j data
│   ├── Scenario 2_care_gap_multi_measure_dataset.xlsx  # Source data (30 members, 73 claims)
│   └── Knowledge Graph - Scenario use cases.pptx
├── .env                                 # Credentials (Neo4j URI, OpenAI key, etc.)
├── .gitignore                           # Keeps .env out of git
├── requirements.txt                     # Python dependencies
└── README.md                            # This file
```

## 🚀 Quick Start

### 1. Prerequisites

- Python 3.8 or higher
- Neo4j Aura account (paid tier recommended for production)
- Azure OpenAI API key (gpt-5-chat deployment)
- Git

### 2. Installation

```bash
# Clone repository
git clone https://github.com/Johnsm123/Knowledge-Graph-AIAgent.git
cd Knowledge-Graph-AIAgent

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

Edit `.env` with your credentials:

```env
# Neo4j Aura Configuration
NEO4J_URI=neo4j+s://<your-instance-id>.databases.neo4j.io
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=<your-secure-password>
NEO4J_DATABASE=neo4j
AURA_INSTANCEID=<your-instance-id>

# Azure OpenAI Configuration
OPENAI_API_KEY=<your-azure-openai-key>
OPENAI_MODEL=gpt-5-chat
ENDPOINT=https://<your-resource>.openai.azure.com/
AZURE_OPENAI_API_VERSION=2025-01-01-preview

# Application Configuration
DEBUG=False
LOG_LEVEL=INFO
```

### 4. Initialize Knowledge Graph

```bash
# Wipe existing data and reload fresh from Excel
python -m src.wipe_and_reload
```

This creates:
- 4 QualityMeasure golden reference nodes (BCS, COL, CCS, CDC-HbA1c)
- 30 Member nodes with demographics
- 18 Provider nodes
- 1 BenefitPlan node
- 73 Claim nodes with CPT/ICD codes
- 10 CareGap nodes (7 open, 3 closed)
- 7 Outreach nodes
- All relationships: ENROLLED_IN, ASSIGNED_TO, HAS_CLAIM, SERVICED_BY, HAS_CARE_GAP, RELATES_TO, TARGETS, CONTACTS

### 5. Run Application

#### Option A: Test Agents on Real Data

```bash
python -m src.test_agents
```

Tests 3 members:
- M0011 (42F) — open BCS gap
- M0002 (41M with diabetes) — open HbA1c gap
- M0009 (71F) — open BCS gap, compliant COL

#### Option B: Use REST API

```bash
python -m src.care_gap_api
```

API will be available at `http://localhost:5001`

## 📡 REST API Endpoints

### Load/Reload Data

```
POST /api/v1/care-gaps/load-data
```

Loads Excel data into Neo4j (safe to call multiple times — uses MERGE)

### Validate Member & Get AI Suggestions

```
POST /api/v1/care-gaps/validate/<member_id>
```

Example:
```bash
curl -X POST http://localhost:5001/api/v1/care-gaps/validate/M0011
```

Returns:
- Member profile (name, age, gender, plan, PCP)
- Applicable quality measures (filtered by age/gender/diagnosis)
- Compliant measures
- Open gaps detected
- Existing graph gaps
- Agent responses (validation, outreach plan, benefit check)

### Get Open Gaps for Member

```
GET /api/v1/care-gaps/<member_id>
```

Returns all open care gaps with resolution guides from golden reference

## 🤖 AI Agents (SelectorGroupChat)

### 1. **Care Gap Validator**

- Validates member compliance against each applicable quality measure
- Explains WHY each gap is open (missing CPT code, expired lookback, no claim)
- States which CPT/HCPCS codes would close each gap
- Provides compliance status per measure

### 2. **Outreach Advisor**

- Prioritises open gaps by urgency (shorter lookback = more urgent)
- Generates specific outreach workflow for each gap
- Provides care manager talking points script
- Recommends outreach channel (Phone for urgent, SMS for scheduling)
- References golden reference resolution guides directly

### 3. **Benefit Checker**

- Confirms whether required service is covered under member's plan
- States member's out-of-pocket cost (Copay/Deductible)
- Checks eligibility restrictions (age, gender, diagnosis)
- Flags if service is NOT covered

### How SelectorGroupChat Works

```
Python code queries Neo4j → builds structured task → LLM orchestrator decides agent order
                                                              ↓
                                                    care_gap_validator responds
                                                              ↓
                                                    LLM orchestrator decides next
                                                              ↓
                                                    outreach_advisor responds
                                                              ↓
                                                    LLM orchestrator decides next
                                                              ↓
                                                    benefit_checker responds
                                                              ↓
                                                    MaxMessageTermination(10) stops
```

The LLM orchestrator reads the conversation and dynamically selects the next agent based on context.

## 📊 Knowledge Graph Schema

### Node Types

- **QualityMeasure**: HEDIS quality measures (golden reference)
  - BCS: Breast Cancer Screening (42-74 Female, 24-month lookback)
  - COL: Colorectal Cancer Screening (45-75 any gender, 120-month lookback)
  - CCS: Cervical Cancer Screening (21-64 Female, 36-month lookback)
  - CDC-HbA1c: HbA1c Testing (18-75 with E11.x diabetes, 12-month lookback)

- **Member**: Individual member records (30 members, M0001-M0030)
- **Provider**: Healthcare providers (18 providers, P1000-P1017)
- **BenefitPlan**: Insurance plan rules (PL-001: $0 copay for preventive)
- **Claim**: Medical encounters (73 claims with CPT/ICD codes)
- **CareGap**: Compliance gaps (10 gaps: 7 open, 3 closed)
- **Outreach**: Care manager contact attempts (7 outreach records)

### Relationships

- `ENROLLED_IN`: Member enrolled in BenefitPlan
- `ASSIGNED_TO`: Member assigned to Provider (PCP)
- `HAS_CLAIM`: Member has Claim
- `SERVICED_BY`: Claim serviced by Provider
- `HAS_CARE_GAP`: Member has CareGap
- `RELATES_TO`: CareGap relates to QualityMeasure
- `TARGETS`: Outreach targets CareGap
- `CONTACTS`: Outreach contacts Member

## 🔄 Example Workflow

```python
from src.care_gap_agents import CareGapAgentSystem

# Initialize agent system
system = CareGapAgentSystem()

# Validate member M0011 and get AI suggestions
result = system.validate_and_suggest("M0011")

# Result contains:
# - member_id, member_name, age, gender
# - applicable_measures (filtered by age/gender/diagnosis)
# - compliant_measures (measures member satisfies)
# - open_gaps_detected (measures member fails)
# - existing_graph_gaps (from database)
# - agent_responses (dict with care_gap_validator, outreach_advisor, benefit_checker)

print(result["member_name"])  # Quinn Iyer
print(result["applicable_measures"])  # ['BCS', 'CCS']
print(result["open_gaps_detected"])  # ['BCS', 'CCS']
print(result["agent_responses"]["care_gap_validator"])  # Validation explanation
print(result["agent_responses"]["outreach_advisor"])  # Outreach plan
print(result["agent_responses"]["benefit_checker"])  # Coverage confirmation
```

## 📈 Query Examples

### Get Member Open Gaps with Resolution Guides

```cypher
MATCH (m:Member {member_id: "M0011"})-[:HAS_CARE_GAP]->(g:CareGap)-[:RELATES_TO]->(q:QualityMeasure)
WHERE g.is_open = true
RETURN g.care_gap_id, q.measure_id, q.name, q.description, q.cpt_codes, q.lookback_months
```

### Find Members Compliant with BCS

```cypher
MATCH (m:Member)-[:HAS_CLAIM]->(c:Claim)
WHERE c.cpt_code IN ['77062', '77061', '77066', '77065', '77063', '77067', 'G0202']
AND c.service_date > date() - duration('P24M')
RETURN DISTINCT m.member_id, m.name, m.age_str, c.service_date
```

### Get All Open Care Gaps by Measure

```cypher
MATCH (g:CareGap)-[:RELATES_TO]->(q:QualityMeasure)
WHERE g.is_open = true
RETURN q.measure_id, q.name, count(g) as open_gap_count
ORDER BY open_gap_count DESC
```

## 🔐 Security Considerations

- Use environment variables for all credentials (never commit `.env`)
- Enable Neo4j Aura encryption (default enabled)
- Implement role-based access control in Neo4j
- Secure API endpoints with authentication tokens
- Comply with HIPAA and data protection regulations
- Regular security audits and updates
- All data operations use MERGE (idempotent, safe for re-runs)

## ⚙️ Configuration Options

### Environment Variables

- `NEO4J_URI`: Neo4j Aura connection URI (neo4j+s://)
- `NEO4J_USERNAME`: Database username (default: neo4j)
- `NEO4J_PASSWORD`: Database password
- `NEO4J_DATABASE`: Database name (default: neo4j)
- `AURA_INSTANCEID`: Neo4j Aura instance ID
- `OPENAI_API_KEY`: Azure OpenAI API key
- `OPENAI_MODEL`: LLM model (gpt-5-chat)
- `ENDPOINT`: Azure OpenAI endpoint URL
- `AZURE_OPENAI_API_VERSION`: API version (2025-01-01-preview)
- `DEBUG`: Enable debug mode (default: False)
- `LOG_LEVEL`: Logging level (DEBUG, INFO, WARNING, ERROR)

## 📚 Additional Resources

- [Neo4j Documentation](https://neo4j.com/docs/)
- [AutoGen Documentation](https://microsoft.github.io/autogen/)
- [Azure OpenAI API Reference](https://learn.microsoft.com/en-us/azure/ai-services/openai/reference)
- [Cypher Query Language](https://neo4j.com/docs/cypher-manual/current/)
- [HEDIS Measures](https://www.ncqa.org/hedis/)

## 🤝 Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Make your changes
4. Commit with clear messages (`git commit -m "Add feature"`)
5. Push to branch (`git push origin feature/your-feature`)
6. Submit a pull request

## 📝 License

This project is licensed under the MIT License - see LICENSE file for details.

## ⚠️ Disclaimer

This system is designed for healthcare quality measure compliance and care gap management. For actual clinical applications, ensure:

- Compliance with healthcare regulations (HIPAA, GDPR, etc.)
- Proper clinical validation and testing
- Integration with licensed healthcare systems
- Appropriate human oversight and approval
- Proper documentation and auditability
- Regular audits of AI recommendations

## 🆘 Support & Troubleshooting

### Neo4j Connection Issues

- Verify NEO4J_URI is correct (neo4j+s:// protocol)
- Check firewall settings allow access to Neo4j Aura
- Confirm credentials are valid
- Test connection: `python -c "from src.neo4j_connection import get_knowledge_graph; kg = get_knowledge_graph()"`

### OpenAI API Issues

- Verify API key is valid
- Check Azure OpenAI deployment name matches OPENAI_MODEL
- Ensure sufficient credits
- Verify endpoint URL is correct
- Test with simple query first

### Agent Communication Issues

- Check OpenAI model availability
- Verify agent configuration in care_gap_agents.py
- Review logs for error details (set LOG_LEVEL=DEBUG)
- Ensure sufficient timeout settings
- Confirm all 3 agents are initialized

### Data Loading Issues

- Close Excel file before running wipe_and_reload
- Verify Excel file path is correct
- Check all required sheets exist (Members, Claims, QualityMeasures, etc.)
- Ensure date formats are consistent (M/D/YYYY or DD-MM-YYYY)

## 📧 Contact

For questions or support, please open an issue on GitHub or contact the development team.

---

**Last Updated**: January 2025
**Version**: 2.0.0
**Status**: Production Ready
