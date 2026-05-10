# HEDIS Care Gap System — Architecture

## High-Level Architecture

```mermaid
flowchart LR
    subgraph Client["👤 Client Layer"]
        UI["React + Vite Frontend<br/>(port 5173)"]
    end

    subgraph Backend["⚙️ Application Layer"]
        API["Flask REST API<br/>care_gap_api.py<br/>(port 5001)"]
        LOADER["Data Loader<br/>care_gap_data_loader.py<br/>Excel → Graph"]
        NEO_OPS["Neo4j Operations<br/>care_gap_neo4j.py<br/>(MERGE / Query layer)"]
    end

    subgraph Agents["🤖 AI Agent Layer (AutoGen 0.7.5)"]
        SELECTOR["SelectorGroupChat<br/>Orchestrator"]
        A1["Eligibility Agent"]
        A2["Care Gap Agent"]
        A3["Recommendation Agent"]
        LLM["Azure OpenAI<br/>GPT-5"]
    end

    subgraph Reference["📚 Golden Reference"]
        HEDIS["hedis_golden_reference.py<br/>BCS · COL · CCS · CDC-HbA1c"]
    end

    subgraph DB["🗄️ Persona DB (Neo4j Aura)"]
        direction TB
        MEMBER["Member"]
        CLAIM["Claim"]
        GAP["CareGap"]
        QM["QualityMeasure"]
        CS["CodeSet"]
        EX["ExclusionCriteria"]
        LIFE["Lifestyle"]
        FAM["FamilyMember"]
        MH["MedicalHistory"]
        EMAIL["Email"]
        APPT["Appointment"]
        OUT["Outreach"]
        PROV["Provider"]
        PLAN["BenefitPlan"]
    end

    UI -- "REST / JSON" --> API
    API --> NEO_OPS
    API -- "validate_and_suggest()" --> SELECTOR
    LOADER --> NEO_OPS
    HEDIS --> LOADER
    HEDIS --> NEO_OPS

    SELECTOR --> A1
    SELECTOR --> A2
    SELECTOR --> A3
    A1 -. "tool calls" .-> NEO_OPS
    A2 -. "tool calls" .-> NEO_OPS
    A3 -. "tool calls" .-> NEO_OPS
    A1 --> LLM
    A2 --> LLM
    A3 --> LLM

    NEO_OPS -- "Bolt (neo4j+s://)" --> DB

    classDef db fill:#0a8a4a,stroke:#0a4a2a,color:#fff
    classDef agent fill:#7a3ec5,stroke:#3a1e6a,color:#fff
    classDef api fill:#1f6feb,stroke:#0d3a8a,color:#fff
    classDef ref fill:#c9881e,stroke:#7a4f0a,color:#fff
    class DB,MEMBER,CLAIM,GAP,QM,CS,EX,LIFE,FAM,MH,EMAIL,APPT,OUT,PROV,PLAN db
    class SELECTOR,A1,A2,A3,LLM agent
    class API,NEO_OPS,LOADER api
    class HEDIS ref
```

## Request Flow — `validate_and_suggest(member_id)`

```mermaid
sequenceDiagram
    participant U as User (UI)
    participant F as Flask API
    participant N as Neo4j Ops Layer
    participant DB as Persona DB
    participant S as SelectorGroupChat
    participant L as Azure OpenAI GPT-5

    U->>F: POST /validate-member/{id}
    F->>N: get_member_profile()
    N->>DB: MATCH (m:Member)…
    DB-->>N: profile + claims
    N-->>F: profile

    F->>N: check_member_exclusions()
    N->>DB: MATCH exclusions
    DB-->>N: matched exclusions

    F->>N: get_applicable_measures(age, gender)
    N->>DB: MATCH QualityMeasure + CodeSets
    DB-->>N: measures + screening options

    F->>N: merge_care_gap() (open gaps)
    N->>DB: MERGE CareGap nodes

    F->>S: run agents
    S->>L: prompts + context
    L-->>S: structured output
    S-->>F: validation + recommendations
    F-->>U: JSON response
```

## Stack Summary

| Layer | Technology |
|---|---|
| Frontend | React + Vite (port 5173) |
| Backend | Flask REST API (port 5001) |
| AI Agents | AutoGen 0.7.5 `SelectorGroupChat` |
| LLM | Azure OpenAI GPT-5 |
| Database | **Persona DB** — Neo4j Aura cloud (Bolt protocol, `neo4j+s://`) |
| Rules Source of Truth | `hedis_golden_reference.py` (Python dict) |
| Startup | `start_servers.bat` |

## Persona DB — Node Inventory

The single Persona DB contains all of:

- **Patient/clinical:** Member, Claim, CareGap, Lifestyle, FamilyMember, MedicalHistoryEntry, Condition
- **Workflow:** Email, Appointment, Outreach
- **Reference (rules-as-graph):** QualityMeasure, CodeSet, ExclusionCriteria, ScreeningOption, ClinicalGuideline, BestPractices
- **Network:** Provider, BenefitPlan

## HEDIS Measures Supported

- **BCS** — Breast Cancer Screening (F, 42–74, 24mo)
- **COL** — Colorectal Cancer Screening (45–75, 120mo, 5 screening options)
- **CCS** — Cervical Cancer Screening (F, 21–64, 36mo, 3 screening options)
- **CDC-HbA1c** — Diabetes Care (18–75 with E11.x, 12mo)
