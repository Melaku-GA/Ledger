# Architecture Documentation

> Mermaid.js diagrams for The Ledger event store system

---

## System Architecture Overview

```mermaid
flowchart TB
    subgraph MCP["MCP Server"]
        direction TB
        Tools["MCP Tools<br/>(Commands)"]
        Resources["MCP Resources<br/>(Queries)"]
    end
    
    subgraph Commands["Command Layer"]
        Handlers["Command Handlers<br/>load → validate → determine → append"]
    end
    
    subgraph EventStore["EventStore Core"]
        Append["append() with<br/>Optimistic Concurrency"]
        LoadStream["load_stream()"]
        LoadAll["load_all()"]
        Upcast["Upcaster Registry"]
        Outbox["Outbox Pattern"]
    end
    
    subgraph Aggregates["Aggregates (Domain Logic)"]
        LA["LoanApplication<br/>loan-{id}"]
        AS["AgentSession<br/>agent-{id}-{session}"]
        CR["ComplianceRecord<br/>compliance-{id}"]
        AL["AuditLedger<br/>audit-{type}-{id}"]
    end
    
    subgraph Projections["Projections (CQRS Read)"]
        Daemon["Projection Daemon<br/>(Async)"]
        AS_Proj["ApplicationSummary"]
        AP_Proj["AgentPerformanceLedger"]
        CA_Proj["ComplianceAuditView<br/>(Temporal)"]
    end
    
    subgraph Database["PostgreSQL"]
        Events["events table<br/>(append-only)"]
        Streams["event_streams table"]
        Checkpoints["projection_checkpoints"]
        OutboxTable["outbox table"]
    end
    
    subgraph Integrity["Integrity Layer"]
        HashChain["SHA-256<br/>Hash Chain"]
        GasTown["Gas Town<br/>Memory Pattern"]
    end
    
    %% MCP to Commands
    Tools --> Handlers
    
    %% Commands to EventStore
    Handlers --> Append
    
    %% EventStore to Aggregates
    Append --> LA
    Append --> AS
    Append --> CR
    Append --> AL
    
    %% EventStore to Database
    Append --> Events
    LoadStream --> Upcast
    Upcast --> Events
    Outbox --> OutboxTable
    
    %% Aggregates enforce business rules
    LA -->|"state machine"| LA
    AS -->|"Gas Town pattern"| AS
    CR -->|"compliance deps"| CR
    
    %% EventStore to Projections
    Events --> Daemon
    LoadAll --> Daemon
    
    %% Daemon to Projections
    Daemon --> AS_Proj
    Daemon --> AP_Proj
    Daemon --> CA_Proj
    
    %% Projections to Checkpoints
    AS_Proj --> Checkpoints
    AP_Proj --> Checkpoints
    CA_Proj --> Checkpoints
    
    %% Queries flow
    Resources --> AS_Proj
    Resources --> AP_Proj
    Resources --> CA_Proj
    
    %% Integrity
    Events --> HashChain
    AS --> GasTown
    
    style Append fill:#f9f,stroke:#333
    style Upcast fill:#ff9,stroke:#333
    style HashChain fill:#9ff,stroke:#333
    style GasTown fill:#9f9,stroke:#333
```

---

## Command/Query Flow (Sequence Diagram)

```mermaid
sequenceDiagram
    participant Agent as AI Agent
    participant MCP as MCP Server
    participant Store as EventStore
    participant DB as PostgreSQL
    participant Proj as Projection Daemon
    
    Note over Agent,Proj: Phase 1: Write Path
    
    Agent->>MCP: submit_application(cmd)
    MCP->>Store: handle_submit_application()
    
    rect rgb(240,248,255)
        Note over Store,DB: Optimistic Concurrency Check
    Store->>DB: SELECT current_version FROM event_streams<br/>WHERE stream_id = 'loan-COMP-001'
    DB-->>Store: version = 3
    
    alt expected_version == actual_version
        Store->>DB: BEGIN TRANSACTION
        Store->>DB: INSERT INTO events (...)
        Store->>DB: UPDATE event_streams SET version = 4
        Store->>DB: INSERT INTO outbox (...)
        Store->>DB: COMMIT
        Store-->>MCP: return new_version = 4
        MCP-->>Agent: {success: true, version: 4}
        
        DB-->>Proj: NOTIFY new_event
        Proj->>Proj: Update ApplicationSummary
        Proj->>DB: UPDATE checkpoint
    else expected_version mismatch
        Store-->>MCP: OptimisticConcurrencyError
        MCP-->>Agent: {error: "version_mismatch", expected: 3, actual: 4}
    end
```

---

## Event Lifecycle Flow

```mermaid
flowchart LR
    subgraph "Event Flow"
        A["ApplicationSubmitted"] --> B["CreditAnalysisRequested"]
        B --> C["CreditAnalysisCompleted"]
        C --> D["FraudScreeningCompleted"]
        D --> E["ComplianceCheckRequested"]
        E --> F["ComplianceRulePassed"]
        F --> G["DecisionGenerated"]
        G --> H["HumanReviewCompleted"]
        H --> I["ApplicationApproved"]
    end
    
    style A fill:#e1f5fe
    style C fill:#fff3e0
    style D fill:#fff3e0
    style F fill:#e8f5e9
    style G fill:#fce4ec
    style I fill:#c8e6c9
```

---

## Upcasting Flow

```mermaid
flowchart TB
    subgraph "Upcasting Flow"
        DB["events table<br/>(stored v1)"] --> Load["load_stream()"]
        Load --> Reg["UpcasterRegistry"]
        Reg --> V1["Check: event_version=1?"]
        V1 -->|Yes| Upcast["Apply v1→v2<br/>upcaster function"]
        V1 -->|No| Return["Return as-is"]
        Upcast --> Return
        Return --> Client["Client receives<br/>v2 payload"]
    end
    
    DB -.->|"Raw row<br/>UNCHANGED"| Verify["Verify: raw DB<br/>still v1"]
    
    style Upcast fill:#ffecb3,stroke:#ff6f00
    style Verify fill:#ffcdd2,stroke:#c62828
```

---

## Gas Town Recovery Pattern

```mermaid
flowchart LR
    subgraph "Gas Town Recovery"
        Start["Agent starts<br/>session"] --> Load["reconstruct_agent_context()"]
        Load --> Events["Load AgentSession<br/>stream events"]
        Events --> Summarize["Summarize old events<br/>into prose"]
        Events --> Preserve["Preserve verbatim<br/>last 3 events"]
        
        alt "Last event was partial"
            Events -->|Yes| Reconcile["Flag:<br/>NEEDS_RECONCILIATION"]
        else "All complete"
            Events -->|No| Ready["Status: READY"]
        end
        
        Reconcile --> Resume["Agent resolves<br/>partial state"]
        Ready --> Resume
        Resume --> Continue["Continue processing"]
    end
    
    style Reconcile fill:#ffcdd2
    style Ready fill:#c8e6c9
```

---

## Hash Chain Integrity

```mermaid
flowchart TB
    subgraph "Hash Chain Integrity"
        Events["Event Stream"] --> Hash1["Hash Event 1"]
        Hash1 --> Hash2["Hash Event 2<br/>+ Hash1"]
        Hash2 --> Hash3["Hash Event 3<br/>+ Hash2"]
        Hash3 --> Chain["Chain:<br/>H1, H2, H3..."]
        
        Check["run_integrity_check()"] --> Load["Load all events<br/>since last check"]
        Load --> Compute["Compute<br/>expected_hash"]
        Compute --> Compare["Compare with<br/>stored hash"]
        
        alt "Hash matches"
            Compare --> Valid["chain_valid: true<br/>tamper_detected: false"]
        else "Hash mismatch"
            Compare --> Invalid["chain_valid: false<br/>tamper_detected: true"]
        end
    end
    
    style Valid fill:#c8e6c9
    style Invalid fill:#ffcdd2
```

---

## Aggregate State Machines

```mermaid
flowchart TB
    subgraph "LoanApplication Aggregate"
        LA1["Submitted"]
        LA2["AwaitingAnalysis"]
        LA3["AnalysisComplete"]
        LA4["ComplianceReview"]
        LA5["PendingDecision"]
        LA6a["ApprovedPendingHuman"]
        LA6b["DeclinedPendingHuman"]
        LA7a["FinalApproved"]
        LA7b["FinalDeclined"]
        
        LA1 --> LA2 --> LA3 --> LA4 --> LA5
        LA5 --> LA6a
        LA5 --> LA6b
        LA6a --> LA7a
        LA6b --> LA7b
        
        style LA1 fill:#e3f2fd
        style LA7a fill:#c8e6c9
        style LA7b fill:#ffcdd2
    end
```

```mermaid
flowchart LR
    subgraph "AgentSession Aggregate"
        AS1["ContextLoaded"]
        AS2["Processing"]
        AS3["DecisionEvent"]
        AS1 --> AS2 --> AS3
        
        style AS1 fill:#e8f5e9
    end
```

```mermaid
flowchart LR
    subgraph "ComplianceRecord Aggregate"
        CR1["CheckRequested"]
        CR2a["RulePassed"]
        CR2b["RuleFailed"]
        CR1 --> CR2a
        CR1 --> CR2b
        
        style CR1 fill:#fff3e0
        style CR2a fill:#c8e6c9
    end
```

---

## Database Schema

```mermaid
erDiagram
    events ||--o{ outbox : contains
    event_streams ||--o{ events : contains
    events {
        uuid event_id PK
        text stream_id FK
        bigint stream_position
        bigint global_position
        text event_type
        smallint event_version
        jsonb payload
        jsonb metadata
        timestamptz recorded_at
    }
    
    event_streams {
        text stream_id PK
        text aggregate_type
        bigint current_version
        timestamptz created_at
        timestamptz archived_at
        jsonb metadata
    }
    
    projection_checkpoints {
        text projection_name PK
        bigint last_position
        timestamptz updated_at
    }
    
    outbox {
        uuid id PK
        uuid event_id FK
        text destination
        jsonb payload
        timestamptz created_at
        timestamptz published_at
        smallint attempts
    }
```

---

## MCP Tool/Resource Architecture

```mermaid
flowchart TB
    subgraph "MCP Server"
        subgraph "Tools (Commands)"
            T1["submit_application"]
            T2["record_credit_analysis"]
            T3["record_fraud_screening"]
            T4["record_compliance_check"]
            T5["generate_decision"]
            T6["record_human_review"]
            T7["start_agent_session"]
            T8["run_integrity_check"]
        end
        
        subgraph "Resources (Queries)"
            R1["ledger://applications/{id}"]
            R2["ledger://applications/{id}/compliance"]
            R3["ledger://applications/{id}/audit-trail"]
            R4["ledger://agents/{id}/performance"]
            R5["ledger://agents/{id}/sessions/{session_id}"]
            R6["ledger://ledger/health"]
        end
    end
    
    subgraph "Backing Stores"
        Proj1["ApplicationSummary"]
        Proj2["ComplianceAuditView"]
        Proj3["AgentPerformanceLedger"]
        Streams["Event Streams"]
    end
    
    T1 --> Streams
    T2 --> Streams
    T3 --> Streams
    T4 --> Streams
    T5 --> Streams
    T6 --> Streams
    T7 --> Streams
    T8 --> Streams
    
    R1 --> Proj1
    R2 --> Proj2
    R3 --> Streams
    R4 --> Proj3
    R5 --> Streams
    R6 --> Proj1
```

---

## Projection Daemon Architecture

```mermaid
flowchart TB
    subgraph "Projection Daemon"
        Poll["Poll events from<br/>last checkpoint"]
        Batch["Batch process<br/>events"]
        Route["Route to<br/>subscribed projections"]
        Update["Update<br/>checkpoints"]
        Metrics["Expose lag<br/>metrics"]
        
        Poll --> Batch --> Route --> Update --> Metrics --> Poll
    end
    
    subgraph "Projections"
        P1["ApplicationSummary<br/>SLO: <50ms lag"]
        P2["AgentPerformanceLedger<br/>SLO: <50ms lag"]
        P3["ComplianceAuditView<br/>SLO: <200ms lag"]
    end
    
    Route -->|"events"| P1
    Route -->|"events"| P2
    Route -->|"events"| P3
    
    P1 -->|"checkpoint"| Check["projection_checkpoints"]
    P2 -->|"checkpoint"| Check
    P3 -->|"checkpoint"| Check
```

---

## What-If Projection (Bonus Phase 6)

```mermaid
flowchart TB
    subgraph "What-If Projector"
        Load["Load events up to<br/>branch point"] --> Branch["Branch point"]
        
        Branch --> Real["Real events"]
        Branch --> CF["Inject counterfactual<br/>events"]
        
        Real --> Replay["Replay events"]
        CF --> Replay
        
        Replay --> Proj["Apply to projections"]
        Proj --> Compare["Compare real vs<br/>counterfactual"]
        
        style CF fill:#fff3e0
        style Compare fill:#e1f5fe
    end
    
    subgraph "Output"
        Compare --> Result["WhatIfResult<br/>real_outcome<br/>counterfactual_outcome<br/>divergence_events"]
    end
```
