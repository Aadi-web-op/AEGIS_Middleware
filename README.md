# AEGIS Middleware & Decision Graph

> **Open-Source Uncertainty Middleware for AI Systems**
> 
> *Aegis evaluates whether an AI-generated answer is sufficiently supported by the available evidence before it reaches the user, deciding whether to **ANSWER**, **CAVEAT**, **ESCALATE** to human verification, or **ABSTAIN**.*

---

## What is the Aegis Decision Graph?

The **Aegis Decision Graph (Neo4j Add-on)** provides visual explainability and cross-decision intelligence:
1. **Explanation View (Single Decision):** For every decision, Aegis draws the exact evidence trail: the user question, claims in the answer, supporting and contradicting evidence, and the source document and version.
   - Green edges (`SUPPORTED_BY`): chunk directly backs the claim.
   - Red edges (`CONTRADICTED_BY` / `CONFLICTS_WITH`): chunk disagrees or contradicts another source.
   - Dashed arrows (`SUPERSEDES`): newer document version replacing an older one.
2. **Cross-Decision Intelligence (Neo4j):** As decisions occur, traces are merged into a local Neo4j graph store to answer systemic questions across all decisions:
   - *Which document pairs conflict most often?*
   - *Which outdated documents are still being retrieved when newer versions exist?*
   - *Which knowledge gaps trigger ABSTAIN most often?*
   - *If a document turns out to be wrong, which past decisions relied on it?*
   - *Which escalations share one common root cause?*

### Critical Design Rules
* **Neo4j is never in the decision path:** Graph writing is asynchronous and non-blocking (`safe_write_trace`). If Neo4j is offline or slow, decisions and UI traces return with zero delay.
* **Privacy-First:** Previews are strictly capped at 120 characters; full document text is never stored in Neo4j.
* **Idempotent Writes:** Nodes and edges are merged on unique identities (`request_id`, `id`), so re-evaluations create zero duplicates.

---

## Quickstart

### 1. Launch Neo4j with Docker Compose
```bash
docker compose up -d
```
Neo4j Browser will be available at [http://localhost:7474](http://localhost:7474) (credentials: `neo4j` / `password`).
The initial schema (constraints and indexes) is located at `scripts/schema.cypher`.

### 2. Run the Benchmark Dev Set & Seed Neo4j
```bash
python -m scripts.seed_neo4j
```
This runs the development benchmark cases through Aegis and populates the Decision Graph in Neo4j.

### 3. Run the 20-Case Explanation Check
```bash
python -m scripts.explanation_check
```
Scores whether every decision headline and reason matches the labelled failure mode across all 20 benchmark cases.

---

## Running Tests

Run the unit and integration test suite:
```bash
pytest tests/
```
All graph tests (sink, builder, schema, insight queries, and seeding) run against fake drivers and require no running Neo4j container.

---

## Demo & Pitch Guide
For the full three-minute presentation walkthrough and judge Q&A drills, see [docs/demo_script.md](docs/demo_script.md).
