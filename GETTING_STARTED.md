# Getting Started Guide - Medical AI Agent System

## 📖 Table of Contents

1. [Prerequisites](#prerequisites)
2. [Neo4j Aura Setup](#neo4j-aura-setup)
3. [Project Installation](#project-installation)
4. [OpenAI Configuration](#openai-configuration)
5. [First Run](#first-run)
6. [Common Tasks](#common-tasks)
7. [Troubleshooting](#troubleshooting)

---

## Prerequisites

Before starting, ensure you have:

- Python 3.8+
- pip (Python package manager)
- A text editor or IDE (VS Code recommended)
- Internet connection
- Accounts for:
  - [Neo4j Aura](https://neo4j.com/cloud/aura/) (free tier available)
  - [OpenAI](https://platform.openai.com/) (API key required)

---

## Neo4j Aura Setup

### Step 1: Create Neo4j Aura Instance

1. Go to [neo4j.com/cloud/aura](https://neo4j.com/cloud/aura/)
2. Sign up for a free account
3. Create a new AuraDB instance:
   - Choose your region
   - Select free tier (3GB)
   - Name it (e.g., "medical-ai")
   - Click "Create"
4. Wait for instance to start (usually 1-2 minutes)

### Step 2: Get Connection Details

1. In Neo4j Aura console, locate your instance
2. Click "Copy connection URI" and save it
3. Note the secure connection format: `neo4j+s://xxxx.neo4j.io`
4. Set a password and save it

### Step 3: Test Connection

In your terminal, you can verify connection details are correct by checking the `.env` file later.

---

## Project Installation

### Step 1: Clone or Download Project

```bash
# If cloning from git
git clone <repository-url>
cd knowledge-graph-AIAgents

# Or if downloading as ZIP
# Extract the ZIP file and navigate to the folder
cd knowledge-graph-AIAgents
```

### Step 2: Create Python Virtual Environment

```bash
# Windows
python -m venv venv
venv\Scripts\activate

# macOS/Linux
python3 -m venv venv
source venv/bin/activate
```

### Step 3: Install Dependencies

```bash
pip install -r requirements.txt
```

Installation will take 2-3 minutes. Main packages:

- `pyautogen` - Multi-agent framework
- `neo4j` - Neo4j driver
- `openai` - OpenAI API
- `flask` - Web framework

---

## OpenAI Configuration

### Step 1: Get OpenAI API Key

1. Go to [platform.openai.com](https://platform.openai.com/)
2. Sign in or create account
3. Navigate to "API keys"
4. Click "Create new secret key"
5. Copy the key (you won't see it again!)

### Step 2: Create OpenAI Config File

The project includes `OAI_CONFIG_LIST` file template. Edit it:

```json
[
  {
    "model": "gpt-4",
    "api_key": "sk-your-actual-key-here",
    "api_type": "openai",
    "api_base": "https://api.openai.com/v1"
  }
]
```

**Option 2: Use Environment Variable**

Instead of editing the file, you can export:

```bash
# Windows PowerShell
$env:OPENAI_API_KEY="sk-your-key"

# Windows CMD
set OPENAI_API_KEY=sk-your-key

# macOS/Linux
export OPENAI_API_KEY=sk-your-key
```

---

## First Run

### Step 1: Configure Environment

Create `.env` file in project root:

```env
NEO4J_URI=neo4j+s://your-instance-id.neo4j.io
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your-secure-password
OPENAI_API_KEY=sk-your-api-key
OPENAI_MODEL=gpt-4
DEBUG=False
LOG_LEVEL=INFO
```

### Step 2: Initialize Database

```bash
python -m src.init_knowledge_graph
```

Expected output:

```
INFO:root:Creating database constraints...
INFO:root:Creating database indexes...
INFO:root:Initializing medical conditions...
INFO:root:Initializing symptoms...
INFO:root:Initializing medications...
INFO:root:Knowledge graph initialization completed successfully!
```

### Step 3: Run Application

```bash
# Option A: Interactive mode
python -m src.main

# Option B: API server
python -m src.api
```

If using API, you'll see:

```
 * Running on http://0.0.0.0:5000
 * Press CTRL+C to quit
```

---

## Common Tasks

### Add a Patient

**Via API:**

```bash
curl -X POST http://localhost:5000/api/v1/patients \
  -H "Content-Type: application/json" \
  -d '{
    "patient_id": "P001",
    "name": "Jane Smith",
    "age": 45,
    "gender": "F"
  }'
```

**Via Python:**

```python
from src.main import create_app

app = create_app()
app.add_patient("P001", "Jane Smith", 45, "F")
```

### Add Medical Condition

**Via API:**

```bash
curl -X POST http://localhost:5000/api/v1/patients/P001/conditions \
  -H "Content-Type: application/json" \
  -d '{
    "condition_id": "COND001",
    "diagnosed_date": "2023-06-15",
    "status": "active"
  }'
```

**Via Python:**

```python
app.add_patient_condition("P001", "COND001", "2023-06-15", "active")
```

### Analyze Patient

**Via API:**

```bash
curl -X POST http://localhost:5000/api/v1/patients/P001/analysis
```

**Via Python:**

```python
analysis = app.analyze_patient("P001")
```

### Get Patient Summary

**Via API:**

```bash
curl http://localhost:5000/api/v1/patients/P001/summary
```

**Via Python:**

```python
summary = app.get_patient_summary("P001")
```

### Generate Care Plan

**Via API:**

```bash
curl http://localhost:5000/api/v1/patients/P001/care-plan
```

**Via Python:**

```python
care_plan = app.generate_care_plan("P001")
```

### Predict Outcomes

**Via API:**

```bash
curl -X POST http://localhost:5000/api/v1/patients/P001/predict-outcomes \
  -H "Content-Type: application/json" \
  -d '{"timeframe_months": 12}'
```

**Via Python:**

```python
outcomes = app.predict_outcomes("P001", timeframe_months=12)
```

---

## Troubleshooting

### Issue: Neo4j Connection Failed

**Error:** `Failed to connect to Neo4j`

**Solutions:**

1. Verify URI is correct: `neo4j+s://` (note the '+s')
2. Check Neo4j Aura instance is running
3. Confirm username and password
4. Check firewall allows outbound port 7687

**Quick Test:**

```python
from src.neo4j_connection import get_knowledge_graph
try:
    kg = get_knowledge_graph()
    print("Connected successfully!")
except Exception as e:
    print(f"Connection error: {e}")
```

### Issue: OpenAI API Error

**Error:** `Invalid API key` or `Rate limit exceeded`

**Solutions:**

1. Verify API key is correct (starts with `sk-`)
2. Check key hasn't expired
3. Ensure OpenAI account has credits
4. Check rate limits at platform.openai.com

**Quick Test:**

```python
import openai
from config.settings import settings
openai.api_key = settings.openai_api_key
response = openai.ChatCompletion.create(
    model="gpt-4",
    messages=[{"role": "user", "content": "Hello"}]
)
print(response)
```

### Issue: Module Not Found Error

**Error:** `ModuleNotFoundError: No module named 'src'`

**Solution:**

1. Ensure you're in the project root directory
2. Verify virtual environment is activated
3. Reinstall dependencies:
   ```bash
   pip install -r requirements.txt
   ```

### Issue: API Port Already in Use

**Error:** `Address already in use`

**Solutions:**

1. Kill existing process:

   ```bash
   # Windows
   netstat -ano | findstr :5000
   taskkill /PID <PID> /F

   # macOS/Linux
   lsof -i :5000
   kill -9 <PID>
   ```

2. Use different port:
   ```python
   # Edit src/api.py
   if __name__ == '__main__':
       app.run(port=5001)  # Use different port
   ```

### Issue: Slow Responses

**Cause:**

- OpenAI API latency (expected for GPT-4)
- Neo4j query complexity
- Network connectivity

**Solutions:**

1. Use GPT-3.5-turbo for faster (less accurate) responses
2. Optimize Neo4j queries
3. Check internet connection
4. Cache results (implemented in utils.py)

---

## Next Steps

Now that you have the system running:

1. **Explore the Knowledge Graph**: Review the schema in `src/kg_schema.py`
2. **Customize Agents**: Modify system prompts in `src/medical_agents.py`
3. **Add More Data**: Use `src/init_knowledge_graph.py` as template
4. **Build UI**: Create frontend using React, Vue, or similar
5. **Deploy**: Consider cloud deployment (AWS, Azure, GCP)

---

## Support & Documentation

- **Main README**: See `README.md` for complete documentation
- **API Docs**: Run API and check endpoint descriptions
- **Neo4j Docs**: https://neo4j.com/docs/
- **AutoGen Docs**: https://microsoft.github.io/autogen/
- **OpenAI Docs**: https://platform.openai.com/docs/

---

## Tips for Best Results

1. **Use GPT-4 for accuracy**, GPT-3.5-turbo for speed/cost
2. **Provide complete patient history** for better analysis
3. **Keep Neo4j indexes updated** for performance
4. **Monitor API usage** to avoid unexpected charges
5. **Test with sample data first** before using real patient data
6. **Document your modifications** to the system
7. **Regular backups** of your Neo4j database

---

**Happy Analyzing! 🏥🤖**
