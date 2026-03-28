# Advanced Usage Guide - Medical AI Agent System

## 📚 Table of Contents

1. [Architecture Deep Dive](#architecture-deep-dive)
2. [Advanced Neo4j Queries](#advanced-neo4j-queries)
3. [Custom Agent Development](#custom-agent-development)
4. [Data Integration](#data-integration)
5. [Performance Optimization](#performance-optimization)
6. [Hospital Deployment](#hospital-deployment)
7. [Security & Compliance](#security--compliance)
8. [Monitoring & Logging](#monitoring--logging)

---

## Architecture Deep Dive

### System Components

```
┌─────────────────────────────────────────────────────────────┐
│                    REST API (Flask)                         │
│         /api/v1/patients, /api/v1/analysis, etc            │
└────────────────┬────────────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────────────┐
│         Medical AI Application (main.py)                    │
│    Orchestrates patient data and analysis workflows        │
└────────────────┬────────────────────────────────────────────┘
                 │
    ┌────────────┴────────────────┐
    │                             │
┌───▼──────────────────┐  ┌──────▼──────────────────┐
│ Medical Agent System │  │ Knowledge Graph Manager │
│ (AutoGen Framework)  │  │ (Neo4j Connection)      │
│                      │  │                         │
│ • Diagnostician      │  │ - Patient nodes         │
│ • History Analyzer   │  │ - Conditions            │
│ • Predictor          │  │ - Medications           │
│ • Advisor            │  │ - Relationships         │
│ • Coordinator        │  │                         │
└──────────┬───────────┘  └──────┬──────────────────┘
           │                      │
           └──────────────┬───────┘
                          │
                ┌─────────▼─────────┐
                │   OpenAI GPT-4    │
                │   (LLM Engine)    │
                └──────────────────┘

                ┌─────────────────────┐
                │  Neo4j Aura Cloud   │
                │  (Knowledge Graph)  │
                └─────────────────────┘
```

### Data Flow

```
User Input
    ↓
API Endpoint
    ↓
Application Layer
    ↓
Agent Selection
    ↓
Neo4j Query Engine
    ↓
OpenAI API
    ↓
Agent Response
    ↓
Response Processing
    ↓
User Output
```

---

## Advanced Neo4j Queries

### 1. Complex Disease Pattern Analysis

```cypher
// Find disease progression patterns with treatment effectiveness
MATCH (p:Patient)-[r1:HAS_CONDITION]->(c1:Condition)
OPTIONAL MATCH (p)-[r2:TAKES_MEDICATION]->(m:Medication)-[r3:TREATS]->(c1)
OPTIONAL MATCH (c1)-[r4:COMPOUNDS]->(c2:Condition;<)-(p)
RETURN
  p.patient_id,
  c1.name as condition,
  r1.diagnosed_date,
  collect(m.name) as medications,
  collect(distinct c2.name) as complications,
  duration.between(datetime(r1.diagnosed_date), datetime()).months as months_since_diagnosis
ORDER BY months_since_diagnosis DESC
```

### 2. Risk Stratification Model

```cypher
// Stratify patients by cumulative risk
MATCH (p:Patient)-[r1:HAS_CONDITION]->(c:Condition)
OPTIONAL MATCH (p)-[r2:HAS_RISK_FACTOR]->(rf:RiskFactor)
WITH p,
     collect({
         condition: c.name,
         severity: c.severity,
         diagnosed: r1.diagnosed_date
     }) as conditions,
     collect(rf.name) as risk_factors,
     p.age as age
WITH p,
     conditions,
     risk_factors,
     age,
     size(conditions) as condition_count,
     size(risk_factors) as risk_count,
     // Calculate risk score
     CASE
       WHEN age > 70 THEN 30
       WHEN age > 60 THEN 20
       WHEN age > 50 THEN 10
       ELSE 0
     END +
     CASE
       WHEN 'Critical' IN [c.severity WHERE c IN conditions] THEN 50
       WHEN 'High' IN [c.severity WHERE c IN conditions] THEN 30
       WHEN 'Medium' IN [c.severity WHERE c IN conditions] THEN 15
       ELSE 0
     END as risk_score
RETURN
  p.patient_id,
  p.name,
  age,
  condition_count,
  risk_count,
  risk_score,
  conditions,
  CASE
    WHEN risk_score >= 70 THEN 'Critical'
    WHEN risk_score >= 50 THEN 'High'
    WHEN risk_score >= 30 THEN 'Medium'
    ELSE 'Low'
  END as risk_level
ORDER BY risk_score DESC
```

### 3. Comorbidity Network Analysis

```cypher
// Analyze disease comorbidities across patient population
MATCH (c1:Condition)<-[:HAS_CONDITION]-(p:Patient)-[:HAS_CONDITION]->(c2:Condition)
WHERE c1 <> c2
WITH c1, c2, count(distinct p) as co_occurrence_count
WHERE co_occurrence_count >= 3  // At least 3 patients with both conditions
RETURN
  c1.name as condition1,
  c2.name as condition2,
  c1.severity as severity1,
  c2.severity as severity2,
  co_occurrence_count,
  // Calculate association strength
  ROUND(100.0 * co_occurrence_count /
    (SELECT count(distinct p2) FROM (MATCH (p2:Patient)-[:HAS_CONDITION]->(c1) RETURN p2) as p2), 2) as percentage_of_condition1_patients
ORDER BY co_occurrence_count DESC
```

### 4. Treatment Pathway Analysis

```cypher
// Analyze successful treatment pathways
MATCH (p:Patient)-[:HAS_CONDITION]->(c:Condition)
OPTIONAL MATCH (p)-[r:TAKES_MEDICATION]->(m:Medication)-[t:TREATS]->(c)
OPTIONAL MATCH (p)-[tw:UNDERWENT_TREATMENT]->(tr:Treatment)
OPTIONAL MATCH (c)<-[comp:COMPOUNDS]-(c2:Condition)
RETURN
  c.name,
  count(distinct p) as num_patients,
  collect(distinct m.name) as medications_used,
  collect(distinct tr.name) as treatments_applied,
  avg(CASE WHEN tw.outcome = 'successful' THEN 1 ELSE 0 END) as success_rate,
  collect(distinct c2.name) as known_complications
```

### 5. Patient Cohort Analysis

```cypher
// Find similar patient cohorts for comparative analysis
MATCH (index_patient:Patient {patient_id: $patient_id})
MATCH (index_patient)-[:HAS_CONDITION]->(shared_condition:Condition)
MATCH (cohort_patient:Patient)-[:HAS_CONDITION]->(shared_condition:Condition)
WHERE cohort_patient <> index_patient
  AND abs(cohort_patient.age - index_patient.age) < 5
OPTIONAL MATCH (cohort_patient)-[r:HAS_CONDITION]->(condition:Condition)
WITH
  index_patient,
  cohort_patient,
  count(shared_condition) as shared_conditions,
  collect(distinct condition.name) as all_conditions
WHERE shared_conditions >= 1
RETURN
  cohort_patient.patient_id,
  cohort_patient.name,
  cohort_patient.age,
  cohort_patient.gender,
  shared_conditions,
  all_conditions
ORDER BY shared_conditions DESC
LIMIT 10
```

---

## Custom Agent Development

### Creating a New Specialized Agent

```python
import autogen

class SpecialistAgent:
    """Template for creating custom specialist agents"""

    def __init__(self, llm_config):
        self.specialist = autogen.AssistantAgent(
            name="specialist_name",
            system_message="""You are a specialist in [your domain].
Your responsibilities:
1. Analyze [specific analysis]
2. Provide [specific recommendations]
3. Consider [important factors]

Response format:
- Finding 1: [description]
- Finding 2: [description]
- Recommendation: [description]""",
            llm_config=llm_config,
        )

    def analyze(self, user_proxy, data):
        """Run analysis"""
        prompt = f"""
        Analyze the following data:
        {data}

        Provide [specific output format]
        """

        user_proxy.initiate_chat(
            self.specialist,
            message=prompt,
        )
```

### Extending Medical Agent System

```python
from src.medical_agents import MedicalAgentSystem

class ExtendedMedicalSystem(MedicalAgentSystem):
    """Extended system with additional agents"""

    def __init__(self):
        super().__init__()
        self._initialize_additional_agents()

    def _initialize_additional_agents(self):
        """Add genetic counselor, pharmacist, etc."""

        self.genetic_counselor = autogen.AssistantAgent(
            name="genetic_counselor",
            system_message="You are a genetic counseling specialist...",
            llm_config=self.llm_config,
        )

        self.pharmacist = autogen.AssistantAgent(
            name="pharmacist",
            system_message="You are a clinical pharmacist specialist...",
            llm_config=self.llm_config,
        )
```

---

## Data Integration

### Importing from EHR Systems

```python
def import_from_hl7(hl7_message: str) -> Dict:
    """Parse HL7 message and import patient data"""
    from hl7.util import parse_file

    parsed = parse_file(hl7_message)

    # Extract patient information
    patient_data = {
        'patient_id': parsed['PID'][0][3],  # MRN
        'name': parsed['PID'][0][5],
        'dob': parsed['PID'][0][7],
        # ... additional fields
    }

    return patient_data

def import_csv_bulk(filepath: str) -> List[Dict]:
    """Import patient data from CSV"""
    import pandas as pd

    df = pd.read_csv(filepath)

    # Validate and transform
    patients = []
    for _, row in df.iterrows():
        patients.append({
            'patient_id': row['MRN'],
            'name': row['Name'],
            'age': row['Age'],
            'gender': row['Gender'],
            # ... additional fields
        })

    return patients

def import_from_fhir(fhir_endpoint: str, token: str) -> List[Dict]:
    """Import FHIR-compliant patient data"""
    import requests

    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(
        f"{fhir_endpoint}/Patient",
        headers=headers
    )

    fhir_bundle = response.json()

    patients = []
    for entry in fhir_bundle.get('entry', []):
        resource = entry['resource']
        patients.append({
            'patient_id': resource['id'],
            'name': resource['name'][0]['given'][0],
            # ... map FHIR to your schema
        })

    return patients
```

### Exporting Data for External Systems

```python
def export_to_hl7(patient_id: str, kg, output_path: str):
    """Export patient data in HL7 format"""
    import hl7

    patient_history = kg.get_patient_history(patient_id)

    # Build HL7 message
    message = hl7.parse('...')  # Build HL7 structure

    with open(output_path, 'w') as f:
        f.write(str(message))

def export_to_fhir(patient_id: str, kg) -> Dict:
    """Export patient data in FHIR format"""

    patient_history = kg.get_patient_history(patient_id)

    fhir_patient = {
        "resourceType": "Patient",
        "id": patient_id,
        "name": [{"text": "Patient Name"}],
        "condition": [
            {
                "resourceType": "Condition",
                "subject": {"reference": f"Patient/{patient_id}"},
                "code": {"text": condition['name']}
            }
            for condition in patient_history
        ]
    }

    return fhir_patient
```

---

## Performance Optimization

### Database Optimization

```python
# Create advanced indexes
index_queries = """
// Composite indexes for common queries
CREATE INDEX IF NOT EXISTS FOR (p:Patient) ON (p.age, p.gender);
CREATE INDEX IF NOT EXISTS FOR (c:Condition) ON (c.severity, c.name);
CREATE INDEX IF NOT EXISTS FOR (r:RiskFactor) ON (r.name);

// Full-text search index
CREATE FULLTEXT INDEX patient_search FOR (p:Patient) ON EACH [p.name, p.patient_id];
CREATE FULLTEXT INDEX condition_search FOR (c:Condition) ON EACH [c.name, c.description];
"""

# Use EXPLAIN/PROFILE to analyze queries
explain_query = """
PROFILE
MATCH (p:Patient)-[:HAS_CONDITION]->(c:Condition)
WHERE c.severity = 'Critical'
RETURN p, c
"""
```

### Query Caching Strategy

```python
from functools import lru_cache
from datetime import datetime, timedelta

class CachedKnowledgeGraph:
    def __init__(self, kg, cache_ttl_minutes=30):
        self.kg = kg
        self.cache_ttl = timedelta(minutes=cache_ttl_minutes)
        self._cache = {}

    def get_patient_history_cached(self, patient_id: str):
        """Get patient history with caching"""
        cache_key = f"history_{patient_id}"

        if cache_key in self._cache:
            data, timestamp = self._cache[cache_key]
            if datetime.now() - timestamp < self.cache_ttl:
                return data

        data = self.kg.get_patient_history(patient_id)
        self._cache[cache_key] = (data, datetime.now())
        return data

    def invalidate_cache(self, patient_id: str):
        """Clear cache for patient"""
        cache_key = f"history_{patient_id}"
        if cache_key in self._cache:
            del self._cache[cache_key]
```

### Batch Processing

```python
def batch_analyze_patients(patient_ids: List[str], batch_size: int = 10):
    """Analyze multiple patients efficiently"""

    for i in range(0, len(patient_ids), batch_size):
        batch = patient_ids[i:i + batch_size]

        # Process batch in parallel
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=5) as executor:
            results = list(executor.map(analyze_single_patient, batch))

        yield results
```

---

## Hospital Deployment

### Production Configuration

```python
# production_config.py
import os

class ProductionConfig:
    """Production environment configuration"""

    # Neo4j Configuration
    NEO4J_URI = os.getenv('NEO4J_URI')
    NEO4J_USERNAME = os.getenv('NEO4J_USERNAME')
    NEO4J_PASSWORD = os.getenv('NEO4J_PASSWORD')

    # Connection pooling
    NEO4J_POOL_SIZE = 50
    NEO4J_POOL_TIMEOUT = 30

    # API Configuration
    API_WORKERS = 4
    API_TIMEOUT = 300

    # Logging
    LOG_LEVEL = "INFO"
    LOG_FORMAT = "json"  # Structured logging

    # Security
    JWT_SECRET = os.getenv('JWT_SECRET')
    CORS_ORIGINS = os.getenv('CORS_ORIGINS', "*").split(",")

    # Monitoring
    SENTRY_DSN = os.getenv('SENTRY_DSN')
    PROMETHEUS_METRICS = True
```

### Docker Deployment

```dockerfile
# Dockerfile
FROM python:3.10-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:5000/api/v1/health')"

# Run application
CMD ["gunicorn", "--workers", "4", "--bind", "0.0.0.0:5000", "src.api:app"]
```

### Kubernetes Deployment

```yaml
# kubernetes-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: medical-ai-agent
spec:
  replicas: 3
  selector:
    matchLabels:
      app: medical-ai-agent
  template:
    metadata:
      labels:
        app: medical-ai-agent
    spec:
      containers:
        - name: medical-ai
          image: medical-ai-agent:latest
          ports:
            - containerPort: 5000
          env:
            - name: NEO4J_URI
              valueFrom:
                secretKeyRef:
                  name: neo4j-secret
                  key: uri
            - name: OPENAI_API_KEY
              valueFrom:
                secretKeyRef:
                  name: openai-secret
                  key: api-key
          resources:
            requests:
              memory: "2Gi"
              cpu: "1000m"
            limits:
              memory: "4Gi"
              cpu: "2000m"
          livenessProbe:
            httpGet:
              path: /api/v1/health
              port: 5000
            initialDelaySeconds: 30
            periodSeconds: 10
          readinessProbe:
            httpGet:
              path: /api/v1/health
              port: 5000
            initialDelaySeconds: 5
            periodSeconds: 5
```

---

## Security & Compliance

### HIPAA Compliance

```python
# hipaa_compliant.py
import hashlib
import hmac
from datetime import datetime

class HIPAACompliantPatientRegistry:
    """HIPAA-compliant patient data management"""

    def __init__(self, kg, encryption_key: str):
        self.kg = kg
        self.encryption_key = encryption_key
        self.audit_log = []

    def access_patient_record(self, user_id: str, patient_id: str):
        """Log access with audit trail"""

        access_record = {
            'timestamp': datetime.now().isoformat(),
            'user_id': user_id,
            'patient_id': patient_id,
            'action': 'READ',
            'status': 'SUCCESS'
        }

        self.audit_log.append(access_record)

        # Log to external audit system
        self._send_to_audit_system(access_record)

    def _encrypt_pii(self, data: str) -> str:
        """Encrypt personally identifiable information"""
        return hmac.new(
            self.encryption_key.encode(),
            data.encode(),
            hashlib.sha256
        ).hexdigest()

    def deidentify_patient_data(self, patient_data: Dict) -> Dict:
        """Remove/hash sensitive information"""
        return {
            'patient_id': self._encrypt_pii(patient_data['patient_id']),
            'age': patient_data.get('age'),  # Age okay as general category
            'gender': patient_data.get('gender'),  # General demographic ok
            # Don't include: name, SSN, addresses, phone numbers, etc.
        }
```

### Data Encryption

```python
from cryptography.fernet import Fernet

class EncryptedKnowledgeGraph:
    """Encrypted knowledge graph access"""

    def __init__(self, kg, cipher_suite: Fernet):
        self.kg = kg
        self.cipher = cipher_suite

    def store_encrypted_data(self, key: str, sensitive_data: str):
        """Store encrypted data"""
        encrypted = self.cipher.encrypt(sensitive_data.encode())
        return self.kg.run_query(
            "SET node.encrypted_field = $encrypted",
            {"encrypted": encrypted}
        )

    def retrieve_decrypted_data(self, key: str):
        """Retrieve and decrypt data"""
        result = self.kg.run_query("RETURN node.encrypted_field")
        if result:
            encrypted = result[0]['encrypted_field']
            decrypted = self.cipher.decrypt(encrypted).decode()
            return decrypted
```

### Role-Based Access Control

```python
class RBACPatientRegistry:
    """Role-based access control"""

    ROLES = {
        'doctor': ['read', 'write', 'analyze'],
        'nurse': ['read', 'write'],
        'lab_tech': ['read'],
        'admin': ['read', 'write', 'delete', 'configure'],
        'patient': ['read_own']
    }

    def authorize_action(self, user_role: str, action: str, resource: str) -> bool:
        """Check if user can perform action"""
        allowed_actions = self.ROLES.get(user_role, [])

        # Special case: patient can only read own records
        if user_role == 'patient' and action == 'read_own':
            return resource == f"patient_{self.current_user_id}"

        return action in allowed_actions
```

---

## Monitoring & Logging

### Comprehensive Logging

```python
import logging
import json
from logging.handlers import RotatingFileHandler

def setup_logging():
    """Setup comprehensive logging"""

    logger = logging.getLogger('medical_ai')
    logger.setLevel(logging.DEBUG)

    # Rotating file handler
    handler = RotatingFileHandler(
        'logs/medical_ai.log',
        maxBytes=10*1024*1024,  # 10MB
        backupCount=10
    )

    # JSON formatter for structured logging
    formatter = logging.Formatter(
        json.dumps({
            'timestamp': '%(asctime)s',
            'level': '%(levelname)s',
            'logger': '%(name)s',
            'message': '%(message)s'
        })
    )

    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger

logger = setup_logging()
```

### Performance Monitoring

```python
from prometheus_client import Counter, Histogram, Gauge
import time

# Create metrics
query_latency = Histogram(
    'neo4j_query_latency_seconds',
    'Neo4j query latency',
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1]
)

api_requests = Counter(
    'api_requests_total',
    'Total API requests',
    ['method', 'endpoint', 'status']
)

active_analyses = Gauge(
    'active_analyses',
    'Number of active patient analyses'
)

def monitor_query_execution(query_name: str):
    """Decorator for monitoring query execution"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                duration = time.time() - start
                query_latency.observe(duration)
                logger.info(f"Query {query_name} took {duration:.2f}s")
        return wrapper
    return decorator
```

---

**Continue reading the main README.md for additional information.**
