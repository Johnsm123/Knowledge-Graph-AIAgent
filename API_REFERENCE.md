# API Reference - Medical AI Agent System

## Base URL

```
http://localhost:5000/api/v1
```

## Authentication

Currently no authentication. For production, implement Bearer token authentication:

```
Authorization: Bearer <your-token>
```

---

## Endpoints Reference

### Health Check

#### Check System Health

```http
GET /health
```

**Response:**

```json
{
  "status": "healthy",
  "message": "Medical AI Agent System is running"
}
```

**Status Codes:**

- `200 OK` - System is running

---

### Patient Management

#### Create Patient

```http
POST /patients
Content-Type: application/json

{
  "patient_id": "P001",
  "name": "John Doe",
  "age": 55,
  "gender": "M"
}
```

**Request Fields:**
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| patient_id | string | Yes | Unique patient identifier |
| name | string | Yes | Patient full name |
| age | integer | Yes | Patient age in years |
| gender | string | Yes | M, F, or Other |

**Response:**

```json
{
  "status": "success",
  "message": "Patient P001 added successfully"
}
```

**Status Codes:**

- `201 Created` - Patient added
- `400 Bad Request` - Missing fields
- `500 Internal Server Error` - Database error

**Example:**

```bash
curl -X POST http://localhost:5000/api/v1/patients \
  -H "Content-Type: application/json" \
  -d '{
    "patient_id": "P001",
    "name": "John Smith",
    "age": 45,
    "gender": "M"
  }'
```

---

#### Add Medical Condition

```http
POST /patients/{patient_id}/conditions
Content-Type: application/json

{
  "condition_id": "COND001",
  "diagnosed_date": "2023-01-15",
  "status": "active"
}
```

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| patient_id | string | The patient ID |

**Request Fields:**
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| condition_id | string | Yes | Medical condition identifier |
| diagnosed_date | string | Yes | Date in YYYY-MM-DD format |
| status | string | Yes | active, resolved, or chronic |

**Valid Condition IDs:**

- `COND001` - Type 2 Diabetes
- `COND002` - Hypertension
- `COND003` - Asthma
- `COND004` - Coronary Artery Disease

**Response:**

```json
{
  "status": "success",
  "message": "Condition added to patient P001"
}
```

**Example:**

```bash
curl -X POST http://localhost:5000/api/v1/patients/P001/conditions \
  -H "Content-Type: application/json" \
  -d '{
    "condition_id": "COND001",
    "diagnosed_date": "2023-06-15",
    "status": "active"
  }'
```

---

#### Get Patient Summary

```http
GET /patients/{patient_id}/summary
```

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| patient_id | string | The patient ID |

**Response:**

```json
{
  "patient_id": "P001",
  "medical_history": [
    {
      "patient_id": "P001",
      "patient_name": "John Doe",
      "condition_id": "COND001",
      "condition_name": "Type 2 Diabetes",
      "diagnosed_date": "2023-01-15",
      "status": "active",
      "severity": "High"
    }
  ],
  "similar_patients": [
    {
      "patient_id": "P002",
      "patient_name": "Jane Smith",
      "common_conditions": 2,
      "age": 54,
      "gender": "F"
    }
  ],
  "status": "success"
}
```

**Example:**

```bash
curl http://localhost:5000/api/v1/patients/P001/summary
```

---

### Analysis & Predictions

#### Analyze Patient

```http
POST /patients/{patient_id}/analysis
```

**Description:**
Performs comprehensive patient analysis using all AI agents:

- Medical diagnosis
- Medical history analysis
- Disease consequence prediction
- Prevention recommendations
- Hospital coordination

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| patient_id | string | The patient ID |

**Response:**

```json
{
  "patient_id": "P001",
  "status": "completed",
  "analysis": "AI agent analysis results..."
}
```

**Time Required:** 1-3 minutes for comprehensive analysis

**Example:**

```bash
curl -X POST http://localhost:5000/api/v1/patients/P001/analysis
```

---

#### Predict Future Outcomes

```http
POST /patients/{patient_id}/predict-outcomes
Content-Type: application/json

{
  "timeframe_months": 12
}
```

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| patient_id | string | The patient ID |

**Request Fields (Optional):**
| Field | Type | Default | Description |
|-------|------|---------|-------------|
| timeframe_months | integer | 12 | Prediction timeframe in months |

**Response:**

```json
{
  "patient_id": "P001",
  "timeframe_months": 12,
  "status": "completed"
}
```

**Example:**

```bash
curl -X POST http://localhost:5000/api/v1/patients/P001/predict-outcomes \
  -H "Content-Type: application/json" \
  -d '{"timeframe_months": 24}'
```

---

#### Generate Care Plan

```http
GET /patients/{patient_id}/care-plan
```

**Description:**
Generates comprehensive care and prevention plan including:

- Immediate interventions
- Short-term strategies
- Long-term prevention
- Lifestyle modifications
- Medication management
- Monitoring schedule

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| patient_id | string | The patient ID |

**Response:**

```json
{
  "patient_id": "P001",
  "status": "completed"
}
```

**Example:**

```bash
curl http://localhost:5000/api/v1/patients/P001/care-plan
```

---

#### Export Analysis

```http
GET /patients/{patient_id}/export?filepath=output/analysis.json
```

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| patient_id | string | The patient ID |

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| filepath | string | output/{patient_id}\_analysis.json | Output file path |

**Response:**

```json
{
  "status": "success",
  "message": "Analysis exported to output/patient_analysis.json"
}
```

**Example:**

```bash
curl "http://localhost:5000/api/v1/patients/P001/export?filepath=output/my_analysis.json"
```

---

## HTTP Status Codes

| Code | Status                | Description                   |
| ---- | --------------------- | ----------------------------- |
| 200  | OK                    | Request successful            |
| 201  | Created               | Resource created successfully |
| 400  | Bad Request           | Invalid request parameters    |
| 404  | Not Found             | Resource not found            |
| 500  | Internal Server Error | Server error                  |

---

## Error Handling

All error responses follow this format:

```json
{
  "status": "error",
  "message": "Description of what went wrong"
}
```

### Example Error Response:

```json
{
  "error": "Missing required fields",
  "required": ["patient_id", "name", "age", "gender"]
}
```

---

## Request/Response Examples

### Complete Workflow

**1. Create Patient**

```bash
curl -X POST http://localhost:5000/api/v1/patients \
  -H "Content-Type: application/json" \
  -d '{
    "patient_id": "P123",
    "name": "Robert Johnson",
    "age": 62,
    "gender": "M"
  }'
```

**2. Add Condition**

```bash
curl -X POST http://localhost:5000/api/v1/patients/P123/conditions \
  -H "Content-Type: application/json" \
  -d '{
    "condition_id": "COND002",
    "diagnosed_date": "2022-03-20",
    "status": "active"
  }'
```

**3. Get Summary**

```bash
curl http://localhost:5000/api/v1/patients/P123/summary
```

**4. Run Analysis**

```bash
curl -X POST http://localhost:5000/api/v1/patients/P123/analysis
```

**5. Predict Outcomes**

```bash
curl -X POST http://localhost:5000/api/v1/patients/P123/predict-outcomes \
  -H "Content-Type: application/json" \
  -d '{"timeframe_months": 12}'
```

**6. Get Care Plan**

```bash
curl http://localhost:5000/api/v1/patients/P123/care-plan
```

**7. Export Results**

```bash
curl "http://localhost:5000/api/v1/patients/P123/export?filepath=output/robert_analysis.json"
```

---

## Rate Limiting

No rate limiting currently implemented. For production, add:

```python
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)

@limiter.limit("5 per minute")
@app.route('/api/v1/patients/<patient_id>/analysis', methods=['POST'])
def analyze_patient(patient_id):
    ...
```

---

## Pagination

Response pagination (for future enhancement):

```
GET /patients?page=1&limit=20&filter=active
```

---

## Data Types

### Date Format

- All dates: `YYYY-MM-DD` (ISO 8601)
- Example: `2023-01-15`

### Gender

- Valid values: `M`, `F`, `Other`
- Case-insensitive in requests

### Condition Status

- Valid values: `active`, `resolved`, `chronic`, `inactive`
- Case-insensitive in requests

### Severity Levels

- `Critical`
- `High`
- `Medium`
- `Low`

---

## Common Workflows

### Workflow 1: New Patient Assessment

```
POST /patients → POST /conditions → GET /summary → POST /analysis
```

### Workflow 2: Risk Assessment

```
GET /summary → POST /predict-outcomes → GET /care-plan
```

### Workflow 3: Comparative Analysis

```
GET /summary (multiple patients) → Analysis comparison → Export results
```

---

## cURL Examples

### Python Requests Library

```python
import requests
import json

base_url = "http://localhost:5000/api/v1"

# Create patient
response = requests.post(
    f"{base_url}/patients",
    headers={"Content-Type": "application/json"},
    json={
        "patient_id": "P001",
        "name": "Jane Doe",
        "age": 55,
        "gender": "F"
    }
)
print(response.json())

# Get summary
response = requests.get(f"{base_url}/patients/P001/summary")
print(response.json())

# Run analysis
response = requests.post(f"{base_url}/patients/P001/analysis")
print(response.json())
```

### JavaScript (Fetch)

```javascript
const baseUrl = "http://localhost:5000/api/v1";

// Create patient
fetch(`${baseUrl}/patients`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    patient_id: "P001",
    name: "Jane Doe",
    age: 55,
    gender: "F",
  }),
})
  .then((r) => r.json())
  .then((data) => console.log(data));

// Get summary
fetch(`${baseUrl}/patients/P001/summary`)
  .then((r) => r.json())
  .then((data) => console.log(data));
```

---

## Troubleshooting

### Connection Refused

**Error:** `Connection refused`
**Solution:** Ensure API is running: `python -m src.api`

### Timeout

**Error:** Analysis requests timing out
**Solution:** GPT-4 analysis can take 1-3 minutes. Increase timeout in client.

### Invalid Patient ID

**Error:** Returns empty results
**Solution:** Verify patient was created: `GET /patients/{id}/summary`

### Missing Conditions

**Error:** Analysis returns incomplete data
**Solution:** Add medical conditions before analysis: `POST /conditions`

---

## API Versioning

Current version: `v1`

Future versions will be accessible at:

- `GET /api/v2/patients`
- `GET /api/v3/patients`

Backwards compatibility will be maintained for at least 2 major versions.

---

**Last Updated: March 2026**
**Version: 1.0.0**
