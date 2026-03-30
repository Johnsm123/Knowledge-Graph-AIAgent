# Quick Reference Guide

## 🚀 Quick Start (5 minutes)

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set up environment
cp .env.example .env
# Edit .env with your Neo4j and OpenAI credentials

# 3. Initialize database
python -m src.init_knowledge_graph

# 4. Run system
python -m src.main              # Interactive mode
# OR
python -m src.api               # API server
```

---

## 📋 Command Reference

### Installation

```bash
pip install -r requirements.txt
```

### Database Setup

```bash
python -m src.init_knowledge_graph
```

### Run Application

```bash
# Interactive mode
python -m src.main

# API mode (http://localhost:5000)
python -m src.api
```

### Using Make (if available)

```bash
make help          # Show all commands
make install       # Install dependencies
make setup         # Create .env file
make init          # Initialize database
make run           # Run main app
make run-api       # Run API server
```

---

## 📡 Common API Calls

### Create Patient

```bash
curl -X POST http://localhost:5000/api/v1/patients \
  -H "Content-Type: application/json" \
  -d '{"patient_id":"P001","name":"John Doe","age":55,"gender":"M"}'
```

### Add Condition

```bash
curl -X POST http://localhost:5000/api/v1/patients/P001/conditions \
  -H "Content-Type: application/json" \
  -d '{"condition_id":"COND001","diagnosed_date":"2023-01-15","status":"active"}'
```

### Get Summary

```bash
curl http://localhost:5000/api/v1/patients/P001/summary
```

### Analyze Patient

```bash
curl -X POST http://localhost:5000/api/v1/patients/P001/analysis
```

### Predict Outcomes

```bash
curl -X POST http://localhost:5000/api/v1/patients/P001/predict-outcomes \
  -H "Content-Type: application/json" \
  -d '{"timeframe_months":12}'
```

### Get Care Plan

```bash
curl http://localhost:5000/api/v1/patients/P001/care-plan
```

---

## 🔧 Configuration

### Edit .env File

```env
NEO4J_URI=neo4j+s://your-instance.neo4j.io
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your-password
OPENAI_API_KEY=sk-your-key
OPENAI_MODEL=gpt-4
```

### Edit OAI_CONFIG_LIST

```json
[
  {
    "model": "gpt-4",
    "api_key": "sk-your-key",
    "api_type": "openai",
    "api_base": "https://api.openai.com/v1"
  }
]
```

---

## 🐛 Troubleshooting

| Problem                    | Solution                                   |
| -------------------------- | ------------------------------------------ |
| `ModuleNotFoundError`      | Activate venv: `source venv/bin/activate`  |
| `Neo4j Connection Refused` | Check URI in .env, verify Neo4j is running |
| `OpenAI API Error`         | Verify API key is correct                  |
| `Port Already in Use`      | Change port in `src/api.py`                |
| `Slow Analysis`            | Use GPT-3.5-turbo instead of GPT-4         |

---

## 📂 File Structure

```
src/
  ├── __init__.py              # Package init
  ├── main.py                  # Main app
  ├── api.py                   # API endpoints
  ├── medical_agents.py        # AI agents
  ├── neo4j_connection.py      # DB connection
  ├── kg_schema.py             # DB schema
  ├── init_knowledge_graph.py  # DB init
  └── utils.py                 # Utilities

config/
  ├── __init__.py
  └── settings.py              # Settings

data/                          # Data storage
notebooks/                     # Jupyter notebooks
.env.example                   # Env template
requirements.txt               # Dependencies
README.md                      # Main docs
GETTING_STARTED.md            # Quick start
API_REFERENCE.md              # API docs
```

---

## 🤖 Agents Overview

| Agent                 | Role                | Key Features                             |
| --------------------- | ------------------- | ---------------------------------------- |
| Diagnostician         | Medical diagnosis   | Symptom analysis, differential diagnosis |
| History Analyzer      | Patient history     | Disease progression, medication tracking |
| Consequence Predictor | Outcome prediction  | Complication risk, timeline projection   |
| Prevention Advisor    | Prevention planning | Lifestyle mods, medications, monitoring  |
| Hospital Coordinator  | Care coordination   | Referrals, resource allocation, docs     |

---

## 🗄️ Knowledge Graph Entities

### Nodes

- **Patient**: Individual patient records
- **Condition**: Medical diseases/conditions
- **Medication**: Drug treatments
- **Symptom**: Clinical symptoms
- **LabTest**: Diagnostic tests
- **RiskFactor**: Health risks
- **Prevention**: Preventive measures

### Relationships

- `HAS_CONDITION`: Patient → Condition
- `HAS_SYMPTOM`: Condition → Symptom
- `TAKES_MEDICATION`: Patient → Medication
- `TREATS`: Medication → Condition

---

## 💾 Sample Condition IDs

```
COND001 - Type 2 Diabetes
COND002 - Hypertension
COND003 - Asthma
COND004 - Coronary Artery Disease
```

---

## 📊 Expected Analysis Time

- Initial analysis: **1-3 minutes**
- Outcome prediction: **2-5 minutes**
- Care plan: **1-2 minutes**
- Summary retrieval: **<10 seconds**

---

## 🔗 Useful Links

- [Neo4j Documentation](https://neo4j.com/docs/)
- [AutoGen Docs](https://microsoft.github.io/autogen/)
- [OpenAI API](https://platform.openai.com/)
- [Cypher Query Language](https://neo4j.com/docs/cypher-manual/)

---

## 📞 Support Resources

- **GETTING_STARTED.md**: Initial setup help
- **ADVANCED_USAGE.md**: Advanced features
- **API_REFERENCE.md**: API documentation
- **PROJECT_SUMMARY.md**: Project details

---

## 🎯 Next Steps After Setup

1. ✅ Install dependencies
2. ✅ Configure .env file
3. ✅ Initialize knowledge graph
4. ✅ Add sample patients
5. ✅ Run analyses
6. ✅ Review results
7. ✅ Deploy to production

---

## 💡 Tips

- **Use GPT-4** for accuracy
- **Use GPT-3.5-turbo** for speed/cost
- **Add context** to patient data for better analysis
- **Cache results** to improve performance
- **Monitor API usage** to control costs
- **Regular backups** of Neo4j database

---

**Version: 1.0.0**
**Last Updated: March 2026**
