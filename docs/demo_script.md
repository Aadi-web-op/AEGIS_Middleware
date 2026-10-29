# Aegis Decision Graph: Demo Script & Judge Pitch Guide

> **Pitch Line:**
> *"Aegis does not only decide whether to answer, caveat, escalate or abstain — it shows the exact evidence trail behind each decision and reveals which documents across the organization keep causing trouble."*

---

## 1. Three-Minute Live Demo Flow

### 0:00 – 0:30: The Problem (RAG Fails Silently)
* **Speaker:** "When organizations deploy AI assistants over internal documents, conflicting, stale, or incomplete policies lead to confident hallucinations."
* **Demo Action:** Ask plain RAG:
  > *"How many casual leaves can an employee take?"*
* **System Output:** Plain RAG answers `"18 casual leaves"` with 100% confidence, completely unaware that an active circular states 12.

### 0:30 – 1:15: Aegis Decision & Plain-Language Explanation
* **Speaker:** "Now watch what happens when Aegis sits as middleware between the RAG model and the user."
* **Demo Action:** Submit the same query through Aegis.
* **Aegis Decision:** **`ESCALATE`**
* **Headline:** *"Two of your documents disagree, so a person should check."*
* **Visual Graph View:**
  - **Center:** Claim node: `"Employees get 18 casual leaves"`.
  - **Green line (`SUPPORTED_BY`):** Connects to `policy_2026.pdf (v3)` saying 18.
  - **Red line (`CONTRADICTED_BY` / `CONFLICTS_WITH`):** Connects to `circular_2025.txt` stating 12.
  - **Dashed arrow (`SUPERSEDES`):** Shows `policy_2026` superseding older versions.
  - **Score Bars:** Six signals: Relevance (0.78), Support (0.79), Contradiction (1.00), Freshness (0.90), Completeness (1.00), Clarity (1.00).

### 1:15 – 2:15: Cross-Decision Graph Insights (Neo4j)
* **Speaker:** "A single decision graph explains one answer. But because Aegis streams traces into Neo4j asynchronously, we can analyze systemic document issues across the entire organization."
* **Demo Action:** Switch to the Neo4j Insights Panel and show live query results:
  1. **Conflicting Document Pairs:**
     *"Which documents contradict each other most often?"*
     Shows `hr-policy.pdf` vs `circular_2025.txt` having 3 numeric conflicts. Fix the document pair once, fix dozens of bot answers.
  2. **Outdated Retrieved Documents:**
     *"Which documents are retrieved while a newer version exists?"*
     Identifies obsolete documents that should be retired from vector retrieval.
  3. **ABSTAIN Knowledge Gaps:**
     *"Which topics end in ABSTAIN most often?"*
     Highlights coverage gaps in the knowledge base where users are left without answers.
  4. **Document Blast Radius (The "What if evidence is wrong?" Judge Question):**
     Click on `circular_2025.txt`: instantly lists every past decision that relied on it. If a circular is revoked, you know exactly which past decisions to audit.
  5. **Escalation Root Causes:**
     Groups 20 human escalation tickets back to 1 root-cause circular.

### 2:15 – 3:00: Open Source & Infrastructure Readiness
* **Speaker:** "Aegis is model-agnostic, evidence-aware, and built with production safety rules:"
  - **Zero Latency on Critical Path:** Neo4j runs out-of-band; if Neo4j goes down, decisions still return instantly.
  - **Privacy First:** Only node IDs, versions, and 120-character previews are stored in Neo4j — full document texts never leave local memory.
  - **Idempotent Storage:** Re-running evaluations never produces duplicate graph nodes.

---

## 2. Likely Judge Questions & Answers

### Q1: "Does Neo4j make the decision more accurate?"
**Answer:** "No. We explicitly do not claim that Neo4j improves decision accuracy. Decisions are made at runtime by the Aegis Policy Engine using our six uncertainty signals. Neo4j is our audit and observability store: it delivers explainability, auditability, and corpus-level diagnostics across decisions."

### Q2: "What happens if Neo4j is slow or crashes during evaluation?"
**Answer:** "Neo4j is never in the decision path. The trace JSON is constructed purely in memory and returned directly in `/v1/evaluate`. The Neo4j sink runs best-effort in the background; if Neo4j is offline, the write quietly logs a warning and the user's decision is completely unaffected."

### Q3: "What if the evidence itself is wrong or fraudulent?"
**Answer:** "That is precisely why we built the `impacted_decisions_for_document` query. If an organization discovers a document had an error or was recalled, Aegis traverses `Document -> Evidence -> Claim -> Decision` to identify every single past answer that relied on that document."
