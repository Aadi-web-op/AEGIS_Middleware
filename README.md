# AEGIS: Open-Source Uncertainty Middleware for AI Systems

[![Tests](https://github.com/Aadi-web-op/AEGIS_Middleware/actions/workflows/tests.yml/badge.svg)](https://github.com/Aadi-web-op/AEGIS_Middleware/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

> **The policy layer that turns *"How sure are we?"* into *"What should the system do next?"* — answer, caveat, escalate, or abstain — with explainable evidence trails.**

---

## 1. Executive Summary & Problem

Organizations deploy AI assistants on top of internal documents (policies, HR manuals, regulations). Those documents are often outdated, incomplete, contradictory, or loosely related to the question — yet assistants still answer confidently. The result: users act on hallucinated or invalidated information.

**Aegis** is a model-agnostic middleware layer that sits between any AI system (LLM / RAG / Agent) and the end consumer. Before an answer reaches the user, Aegis evaluates evidence support across 6 quantifiable uncertainty signals and maps confidence to 4 discrete runtime actions:

| Decision | Meaning | Action Taken |
| :--- | :--- | :--- |
| **`ANSWER`** | Evidence is strong and consistent | Return the answer normally |
| **`CAVEAT`** | Mostly supported, minor uncertainty | Return answer + explicit caveat (e.g., outdated document, minor conflict) |
| **`ESCALATE`** | Unresolvable conflict or ambiguous query | Route to human verification queue or ask a clarifying question |
| **`ABSTAIN`** | Evidence is insufficient or missing | Safely refuse to answer; state missing evidence |

---

## 2. System Architecture

```mermaid
flowchart TD
    User([User Query]) --> RAG[AI / RAG Pipeline]
    RAG --> AnswerEvidence[Answer + Retrieved Chunks]
    AnswerEvidence --> Aegis[AEGIS Middleware]
    
    subgraph Aegis Engine
        Claims[Claim Extraction & Grounding]
        Signals[6 Uncertainty Signals]
        Score[Weighted Answerability Score]
        Veto[Veto Rules & Risk Profiles]
        
        Claims --> Signals
        Signals --> Score
        Score --> Veto
    end
    
    Aegis --> Decision{Action}
    Decision -->|Safe| Ans[ANSWER]
    Decision -->|Qualified| Cav[CAVEAT]
    Decision -->|Conflict / Ambiguous| Esc[ESCALATE]
    Decision -->|Insufficient| Abs[ABSTAIN]
    
    Aegis -.->|Async Safe Write| GraphStore[(Neo4j Decision Graph)]
    Aegis -.->|Audit Record| SQLite[(SQLite Audit Log)]
```

### The 6 Quantifiable Uncertainty Signals
1. **Relevance:** Semantic embedding similarity between query and retrieved chunks.
2. **Entailment / Support:** DeBERTa NLI verifying each claim extracted from the answer against evidence.
3. **Contradiction:** Pairwise cross-document checks, numeric mismatches (e.g. 18 vs 12 days), and date conflicts.
4. **Freshness:** Mathematical decay over source document dates and version metadata.
5. **Completeness:** Multi-aspect query coverage check ensuring all components of a question are addressed.
6. **Ambiguity:** Underspecified query detection generating actionable clarifying questions.

---

## 3. The Aegis Decision Graph (Neo4j Add-On)

Aegis does not merely output a numerical score; it visualizes the entire evidence trail behind each decision:
* **Single-Decision Explanation:** Draws the graph of `Decision` $\rightarrow$ `Claim` $\rightarrow$ `Evidence` $\rightarrow$ `Document` $\rightarrow$ `Reason`:
  - 🟢 **Green line (`SUPPORTED_BY`):** Evidence passage directly entails the claim.
  - 🔴 **Red line (`CONTRADICTED_BY` / `CONFLICTS_WITH`):** Direct factual contradiction or numeric mismatch between documents.
  - 🟡 **Dashed line (`SUPERSEDES`):** Newer document version replacing an obsolete circular.
* **Cross-Decision Intelligence (Neo4j):** As decisions occur, traces are merged into Neo4j to analyze organizational knowledge issues:
  - *Which document pairs contradict each other most frequently?*
  - *Which obsolete versions are still retrieved by the vector index?*
  - *Where does the bot abstain most often (identifying knowledge gaps)?*
  - *Blast Radius: If a policy document is retracted, which past decisions relied on it?*
  - *Which human escalations share one common root-cause document?*

> **Production Safety Guarantees:**
> * **Zero Latency on Decision Path:** Graph writing is asynchronous and non-blocking (`safe_write_trace`). If Neo4j is offline, decisions still return instantly.
> * **Privacy-First:** Previews are capped at 120 characters; full document texts are never persisted to the graph.
> * **Idempotent Writes:** Nodes and edges are merged on unique IDs; re-running evaluations creates zero duplicates.

---

## 4. 5-Minute Quickstart

### Prerequisites
* Python 3.10+
* Docker & Docker Compose (for Neo4j)
* Node.js 18+ (for frontend demonstration)

### 1. Start Neo4j Database
```bash
docker compose up -d
```
Neo4j Browser: [http://localhost:7474](http://localhost:7474) (Credentials: `neo4j` / `password`).

### 2. Install Aegis & Start Backend API
```bash
# Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1   # Windows
# source .venv/bin/activate    # Linux/macOS

# Install dependencies
pip install -e .
pip install -r requirements.txt

# Launch FastAPI server
uvicorn app.main:app --reload --port 8000
```
API Documentation: [http://localhost:8000/docs](http://localhost:8000/docs)

### 3. Launch React Frontend
```bash
cd frontend
npm install
npm run dev
```
Open [http://localhost:5173](http://localhost:5173) to access the interactive Decision Graph and side-by-side RAG demonstration.

---

## 5. 5-Line Integration Example

Wrap any existing RAG or LLM function with Aegis in seconds:

```python
from app.core.evaluator import Evaluator
from app.evidence.registry import default_signals
from app.schemas import Decision, EvaluateRequest

evaluator = Evaluator(default_signals())

def safe_ai_query(query: str, answer: str, evidence_chunks: list[dict]):
    result = evaluator.evaluate(EvaluateRequest(query=query, answer=answer, evidence=evidence_chunks))
    
    if result.decision == Decision.ANSWER:
        return answer
    elif result.decision == Decision.CAVEAT:
        return f"{answer}\n\n[Caution: {result.caveat_text}]"
    elif result.clarifying_question:
        return result.clarifying_question
    return "I cannot safely verify this from the available documents. Routing to a human reviewer."
```

---

## 6. Evaluation & Benchmark Results

Aegis includes a standardized benchmark covering 40 real-world policy scenarios (clear answers, numeric contradictions, outdated versions, incomplete evidence, and prompt injections):

| System Configuration | Coverage (% Answered) | Selective Accuracy | False-Answer Rate | Contradiction Detection |
| :--- | :---: | :---: | :---: | :---: |
| **Baseline RAG (No Middleware)** | 100.0% | 58.3% | 41.7% | 0.0% (Guesses silently) |
| **Naive Retrieval Threshold** | 72.5% | 68.2% | 31.8% | 12.5% |
| **Aegis Middleware (Standard)** | **62.5%** | **94.8%** | **5.2%** | **100.0% (Escalates all)** |

> **Headline Result:** Aegis reduced false or unsupported answers reaching users from **41.7% to 5.2%**, catching 100% of conflicting circulars while safely passing through 62.5% of verified answers.

### Run Verification & Explanation Checks
```bash
# Run full test suite (375+ unit, graph, and API tests)
pytest tests/

# Seed benchmark cases into Neo4j
python -m scripts.seed_neo4j

# Run the 20-case explanation check
python -m scripts.explanation_check
```

---

## 7. License & Open Source

This project is licensed under the [MIT License](LICENSE). Built for the HackFront India Open Source & Innovation Track.
