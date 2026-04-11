# iReDev-Agile (CARA)

**CARA** (Collaborative Agile Requirements Agent) is a multi-agent system for automating requirements engineering across the full Agile development lifecycle. Built on top of the iReDev framework, it coordinates specialized LLM-powered agents through LangGraph to produce product backlogs, acceptance criteria, and sprint artifacts — with human review checkpoints at each critical stage.

---

## Overview

Traditional requirements engineering in Agile suffers from high-level, ambiguous initial inputs. CARA addresses this by orchestrating a team of agents that elicit, analyze, document, and validate requirements in a structured, traceable way — grounded in domain knowledge and methodology.

The system is built around three ideas:
- **ReAct loop reasoning** — agents reason step-by-step and select tools dynamically based on context, rather than following a fixed script
- **Dual-tier knowledge retrieval** — static foundational knowledge (domains, standards, methodologies) indexed in pgvector + phase-adaptive RAG filtering so each agent only retrieves what's relevant to its current task
- **Two-level orchestration** — a macro supervisor manages phase transitions (Sprint 0 → Sprint N → Sprint Review), while a micro artifact-driven mechanism routes within each phase based on what's been produced vs. what's missing

---

## Agile Workflow

### Sprint 0 — Discovery & Planning

The process starts when a user submits an initial idea or project brief.

1. **InterviewerAgent** conducts a multi-round dialogue with **EndUserAgent**, extracting formalized requirements incrementally after every stakeholder reply. Each requirement captures its type (functional / non-functional / constraint), priority, source turn, and status.
2. Requirements are conflict-checked in real time. Ambiguous or contradictory items trigger targeted Socratic follow-up questions.
3. When completeness reaches the threshold (default 0.8), the Interviewer finalizes the `interview_record` artifact.
4. **SprintAgent** reads the interview record and generates the initial **Product Backlog**.
5. A human review checkpoint fires. If rejected, the Sprint Agent revises the backlog. Once approved, the Sprint Agent decomposes backlog items into a **Sprint Backlog** for each user story.
6. The Sprint Backlog also goes through human review before the first sprint begins.

### Sprint N — Execution

Each sprint cycle:

1. **AnalystAgent** *(to be implemented)* generates **Acceptance Criteria** for the scheduled user stories, grounded in the backlog and domain knowledge.
2. Human review: if revisions are needed, the Analyst updates the criteria.
3. Developers implement features and submit pull requests.
4. **ReviewerAgent** *(to be implemented)* compares the submitted work against the Acceptance Criteria. If work does not pass, development continues.
5. Once passing, **SprintAgent** updates the Product and Sprint Backlogs to reflect completed items.
6. Human reviewers assess the generated artifacts; Sprint Agent performs further updates if needed.

### Sprint Review — Alignment & Iteration

At the start of each new iteration:

1. A human reviewer evaluates the overall output of the previous sprint.
2. **InterviewerAgent** operates in **consulting mode**, engaging stakeholders to surface new requirements or conflicts.
3. If new requirements or scope changes emerge, the Interviewer coordinates with SprintAgent to update the backlog.
4. If no pending tasks remain, the process terminates.

---

## Agents

| Agent | Status | Role |
|---|---|---|
| **InterviewerAgent** | ✅ Implemented | Conducts requirements interviews, extracts and validates requirements incrementally, produces `interview_record` |
| **EndUserAgent** | ✅ Implemented | Simulates a stakeholder (product manager / domain expert) responding to interview questions |
| **SprintAgent** | 🔧 Stub | Converts interview record into Product Backlog; decomposes into Sprint Backlogs; updates backlogs after each sprint |
| **AnalystAgent** | ⏳ Not yet | Generates Acceptance Criteria for user stories in Sprint N |
| **ReviewerAgent** | ⏳ Not yet | Validates pull requests / developer work against Acceptance Criteria |

---

## Architecture

```
User Input (project brief)
        ↓
[Supervisor] ─────────────────────────────────────────┐
        │                                              │
        ↓                                             END
[InterviewerAgent] ↔ [EndUserAgent]
  (multi-turn interview + incremental extraction)
        │
        ↓ interview_record
[SprintAgent] → Product Backlog
        │
   [Human Review] ─── reject → SprintAgent (revise)
        │ approve
        ↓
   Sprint Backlog
        │
   [Human Review] ─── reject → SprintAgent (revise)
        │ approve
        ↓
[Sprint N loop]
  [AnalystAgent] → Acceptance Criteria
        │
   [Human Review]
        │
  [Developer → PR]
        │
  [ReviewerAgent] → pass/fail
        │ pass
  [SprintAgent] → update backlogs
        │
[Sprint Review]
  [InterviewerAgent (consulting)] ↔ stakeholders
  [SprintAgent] → backlog updates
        │
  next Sprint N or END
```

### Core Systems

**Orchestrator** — LangGraph `StateGraph` with a deterministic supervisor. Phase transitions (Sprint 0 → Sprint N → Sprint Review) are governed at the macro level; within each phase, routing is artifact-driven: the supervisor checks which artifacts exist and which are still missing.

**ThinkModule** — per-agent reasoning layer combining Memory-First RAG with the ReAct execution loop. Before each agent turn, relevant knowledge is retrieved from pgvector and injected into the system prompt. The ReAct loop then runs the agent's tools iteratively until a terminal action fires.

**KnowledgeModule** — singleton pgvector store. Knowledge is partitioned by type (domains, methodologies, standards, templates, strategies) and filtered by process phase (elicitation, analysis, specification, validation) at retrieval time.

**MemoryModule** — three memory backends: short-term conversation buffer (session-scoped), episodic memory (per PR / sprint, PostgreSQL), and semantic memory (settled facts, PostgreSQL with vector search).

**ArtifactPool** — all produced artifacts flow through `WorkflowState["artifacts"]`. The supervisor reads this dict to determine what has been produced and what to do next.

---

## Knowledge Base

Five knowledge categories are loaded and indexed at startup:

- **Domains** — software engineering principles, system architecture, security standards
- **Methodologies** — 5W1H questioning, deployment analysis, security analysis
- **Standards** — IEEE 830 (SRS structure and quality attributes)
- **Templates** — SRS document template
- **Strategies** — MoSCoW prioritization

Knowledge files (YAML/Markdown) are watched by a file-system observer and re-indexed automatically on change.

---

## Human-in-the-Loop

Review checkpoints pause the workflow and wait for human input at:
- Product Backlog generation (Sprint 0)
- Sprint Backlog generation (Sprint 0)
- Acceptance Criteria generation (Sprint N)
- Sprint output review (Sprint Review)

Rejections at any checkpoint automatically reroute the workflow back to the appropriate refinement stage. The system waits indefinitely (configurable timeout) so reviewers can switch context and return later without losing state.

---

## Tech Stack

**Backend** — Python 3.10+, Flask, Flask-Sock (WebSocket), LangGraph, LangChain, PostgreSQL + pgvector, SQLAlchemy

**Frontend** — React 19, Vite, Tailwind CSS, WebSocket client

**LLM Providers** — OpenAI, Anthropic Claude, Google Gemini, HuggingFace / Ollama (local)

**Infrastructure** — Docker Compose (PostgreSQL + pgvector + pgAdmin)

---

## Project Structure

```
├── backend/
│   ├── src/
│   │   ├── agent/          # InterviewerAgent, EndUserAgent, SprintAgent, BaseAgent
│   │   ├── orchestrator/   # LangGraph graph, supervisor, workflow state, flow definitions
│   │   ├── knowledge/      # KnowledgeModule (pgvector indexing + retrieval)
│   │   ├── memory/         # Short-term, episodic, and semantic memory
│   │   ├── think/          # ThinkModule (Memory-First RAG + ReAct loop)
│   │   ├── profile/        # Agent system prompt loader
│   │   └── server/         # Flask REST API, WebSocket handler, auth
│   ├── knowledge/          # YAML knowledge files (domains, methodologies, standards, etc.)
│   ├── prompts/            # Agent profile prompts (.txt)
│   └── config/             # agent_config.yaml, iredev_config.yaml
└── frontend/
    └── src/
        ├── context/        # AuthContext, ChatContext
        ├── hooks/          # useChat, useWebSocket
        ├── services/       # apiClient, chatService, websocketService, tokenStore
        └── components/     # Chat UI, artifact panel, sidebar, settings
```

---

## Paper Reference

This implementation is based on **CARA: Collaborative Agile Requirements Agent**, which extends the iReDev framework with dynamic ReAct reasoning, phase-adaptive RAG, and a two-level Agile orchestration model spanning Sprint 0, Sprint N, and Sprint Review phases.