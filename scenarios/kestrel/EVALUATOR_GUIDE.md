# AEGIS dry run: Kestrel Freight & Logistics

A complete, realistic simulation of AEGIS deployed at a company.

## The company

**Kestrel Freight & Logistics Pvt. Ltd.** (fictional) is a logistics company: about
1,400 employees, 22 branches, HQ in Pune. Three weeks ago it rolled out
**Kestrel Assist**, an internal AI assistant on Teams that answers questions for:

| Channel | Who asks | AEGIS risk profile |
|---|---|---|
| HR helpdesk | Employees: leave, WFH, insurance, probation | `standard` |
| Finance helpdesk | Employees: travel limits, expense claims | `standard` |
| IT helpdesk | Employees: passwords, laptops, phishing | `lenient` (internal FAQ) |
| Customer support | Support agents answering customers: claims, refunds, surcharges, privacy | `strict` (money and legal exposure) |

**AEGIS sits between Kestrel Assist and the person asking.** Every answer the bot
drafts is sent to AEGIS with the passages it retrieved. AEGIS decides:
**ANSWER** (send it), **CAVEAT** (send it with a warning), **ABSTAIN** (don't
answer) or **ESCALATE** (send it to a human). Every decision is written to the
Neo4j knowledge graph.

## The knowledge base (13 documents, 5 departments)

| Department | Document | Version | Effective |
|---|---|---|---|
| HR | Leave Policy (HR/2024/11) | 2024 | 2024-03-01 |
| HR | **Leave Policy, revised (HR/2026/09)** | 2026 | 2026-11-02 · **you upload this one** |
| HR | Employee Handbook | 2025.1 | 2025-06-01 |
| HR | Hybrid Work / WFH Policy | 1.2 | 2025-01-15 |
| HR | Benefits & Group Health Insurance | 2026 | 2026-04-01 |
| Finance | Travel & Expense Policy | 3.0 | 2025-07-01 |
| Finance | Circular FIN/2026/07 (amends hotel limit and claim deadline) | FIN/2026/07 | 2026-10-15 |
| IT | Information Security Policy | 4.1 | 2025-10-01 |
| IT | IT Service Catalogue & SLAs | 2026.2 | 2026-08-10 |
| Customer Ops | Customer SLA | 2026 | 2026-01-01 |
| Customer Ops | Rate Card Q3 2026 | Q3-2026 | 2026-07-01 |
| Customer Ops | Rate Card Q4 2026 (replaces Q3) | Q4-2026 | 2026-10-01 |
| Legal | Data Privacy & Retention Policy | 2.0 | 2025-11-01 |
.00000000000 
PDFs: `scenarios/kestrel/docs/`. The one you upload: `scenarios/kestrel/docs/to-upload/`.

Like most real knowledge bases, it's messy:
* **The new leave policy was published on 2 Nov, but nobody added it to the bot.**
  For three weeks the bot kept telling people "18 casual leaves, carry-forward allowed".
  The new policy says 12, with no carry-forward.
* **The Employee Handbook was never updated.** It still says 18 days and a 6-month
  probation, while the old leave policy says 3 months.
* **A finance circular changed two numbers** in the travel policy (hotel limit
  Rs 6,000 → 7,500, claim deadline 30 → 15 days). Both documents are still live.
* **The Q3 rate card was replaced by Q4**, but the retriever sometimes still picks Q3.
* **Some questions have no document at all** (referral bonus, gratuity,
  night-shift allowance), so the bot makes up an answer.

## What has already happened (the replayed history)

At start-up, **40 real-looking interactions** from the last three weeks were
replayed through AEGIS (`traffic.py`), across all four channels. A reviewer has
already worked two escalations (one resolved, one in review). The rest are waiting.

## Start / stop

```powershell
pwsh -File scenarios\kestrel\start.ps1                    # start (replays history on first run)
pwsh -File scenarios\kestrel\start.ps1 -Fresh             # wipe and start over
pwsh -File scenarios\kestrel\start.ps1 -GroqKey gsk_...   # also enable live "Generate & evaluate"
pwsh -File scenarios\kestrel\stop.ps1                     # stop; switches back to the dev Neo4j
```

Console http://localhost:8080 · API docs http://localhost:8001/docs · Neo4j Browser http://localhost:7474 (user `neo4j`, password in `.env.local`)

**Sign-in:** the console now requires a login. The admin account comes from `scenarios/kestrel/.env.local` (gitignored; `AEGIS_ADMIN_EMAIL` / `AEGIS_ADMIN_PASSWORD`). Use `http://localhost:8080`, not `127.0.0.1`, so the session cookie reaches the API. Security check: `python scripts/security_check.py` (report in `docs/security/SECURITY_CHECK.md`).

---

## Walkthrough (about 25 minutes)

### Step 1: Sign in, then health check (System page)
Sign in with the admin account. Then check that the API is online, all 6 signals are listed, and **Neo4j shows connected**.

### Step 2: What happened in three weeks (Overview and Decisions pages)
* 40 decisions: **12 ANSWER, 8 CAVEAT, 11 ESCALATE, 9 ABSTAIN**.
* Open a few on the Decisions page:
  * *"What is the sum insured under the group medical policy?"* The bot said Rs 10 lakh and the
    document says Rs 5 lakh, so it was **ESCALATED**. The contradicting number is highlighted.
  * *"What is the hotel limit per night in Mumbai?"* The bot said Rs 6,000, which is outdated
    because the October circular says Rs 7,500. **ESCALATED** with `CONTRADICTION`.
  * *"What is the employee referral bonus?"* The bot invented Rs 25,000 and no document covers
    it, so it **ABSTAINED**.
  * *"How many casual leaves do I get in a year?"* **ANSWER**, "18 days". This was correct against
    what the bot knew at the time. Keep it in mind for Step 5.

### Step 3: Human review (Escalations page)
* 11 escalations: 1 resolved (hotel limit, with a note from Finance), 1 in review (sum insured),
  and 9 pending.
* Open a pending one, read the question, the bot's answer and the reason, then **resolve or
  dismiss it with a note**. This is the audit trail.

### Step 4: What the knowledge graph already knows (Intelligence and Graph pages)
The Intelligence page should show:
* **Contradiction hotspot:** `finance_circular_fin_2026_07.pdf` conflicts with `travel_expense_policy.pdf@3.0`.
* **Escalation root cause:** both of those documents are behind 3 escalations each.
* **Stale version in use:** superseded `rate_card.pdf@Q3-2026` is still being retrieved.
* **Knowledge gaps:** referral bonus, gratuity and night-shift allowance questions rarely get
  an answer, so HR should write those documents.

On the Graph page, open the Mumbai hotel decision:
Decision → Claim → CONTRADICTED_BY → Evidence → FROM → Document, plus the CONFLICTS_WITH edge.

### Step 5: HR publishes the new leave policy (Documents page, the key moment)
**Ingest a document version → Upload PDF**

| Field | Value |
|---|---|
| File | `scenarios/kestrel/docs/to-upload/HR_Leave_Policy_2026_NEW.pdf` |
| Source | `leave_policy.pdf` (must match exactly) |
| Version | `2026` |
| Date | `2026-11-02` |

Expected result:
* **Change detected:** this replaces version 2024 of `leave_policy.pdf`.
* **7 past decisions affected**: everything the bot told employees from the old policy
  (casual leave, carry-forward, paternity, notice period) is now listed. This is the
  "who did we tell the wrong thing" list.
* Go back to **Intelligence**: a new finding, *"Superseded leave_policy.pdf@2024 is still being
  retrieved"*. On the Graph page, `leave_policy@2026 SUPERSEDES leave_policy@2024`.

### Step 6: Try it yourself (Evaluate page → "Bring your own answer")
You play the chatbot. Put a **blank line between passages**. Leave time-sensitive **off**.
Profile `standard` unless stated.

| # | Question | Answer (what the bot says) | Evidence (passages) | Expect |
|---|---|---|---|---|
| 1 | How many casual leave days do employees get per year? | Employees are entitled to 12 days of casual leave per calendar year, and unused casual leave lapses on 31 December. | Employees are entitled to 12 days of casual leave per calendar year. Carry-forward of casual leave is no longer permitted. Unused casual leave lapses on 31 December. | **ANSWER** |
| 2 | How many casual leave days do employees get per year? | Employees get 18 days of casual leave per year. | Passage 1: Employees are entitled to 18 days of casual leave per calendar year. Unused casual leave may be carried forward for up to 6 months into the next year. Then a blank line, then passage 2: the 12-day text from row 1. | **ESCALATE** (old vs new) |
| 3 | How many casual leave days do employees get per year? | Employees get 12 days of casual leave per year. | The 12-day text from row 1, a blank line, then: Employees get 18 days of casual leave every year, in addition to earned leave and sick leave. | **ESCALATE** (the handbook was never updated) |
| 4 | What is the hotel limit per night in Bengaluru? | The hotel limit in metro cities is Rs 7,500 per night. | With effect from 15 October 2026, the hotel limit in metro cities is revised to Rs 7,500 per night. | **ANSWER** |
| 5 | What is the hotel limit per night in Bengaluru? | The hotel limit in metro cities is Rs 10,000 per night. | Same as row 4 | **ESCALATE** (invented number) |
| 6 | Can a customer raise a damage claim 10 days after delivery? (profile **strict**) | The customer can raise the damage claim and get a full refund. | Damage claims must be raised within 7 days of delivery, with photographs of the package and the proof of delivery. | **ESCALATE** |
| 7 | What is the employee referral bonus? | The referral bonus is Rs 25,000. | Leave empty | **ABSTAIN** |

On each result, check the decision, the headline, the 6 signal bars, the reasons, the per-claim
status with the **evidence span highlighted**, and the "what would change this decision" insight.
Each one also appears on the Escalations, Decisions and Graph pages.

### Step 6b: Fact Lock: approved facts that retrieval cannot override (Fact Lock page)
Kestrel has locked 11 key facts, such as prices, limits and deadlines, each at a risk level:

| Level | Meaning |
|---|---|
| L1 Info | A wrong value gets a correction note |
| L2 Operational | A wrong value is corrected automatically |
| L3 Commitment | A wrong value is blocked and sent to a person |
| L4 Regulated | A wrong or uncited value is blocked until approved |

1. Press **Check** on the pre-filled example, "damage claim within 14 days". The decision is **ESCALATE**, because the locked value is 7 days at level L3.
2. Try `Expense claims must be submitted within 30 days.` It returns **CAVEAT**, plus a corrected answer saying 15 days, because this fact is level L2.
3. Try `The hotel limit is Rs 7,500 per night in metro cities and Rs 4,000 per night in other cities.` Both facts are confirmed, and the two values are not mixed up.
4. Click **Past answers** on *sum insured*. AEGIS re-checks every stored answer and finds the bot's earlier "Rs 10 lakh" answer.
5. Click **Change value** on *casual leave*: 18 days → `12 days`, version `2026`. This is the 2026 policy. The past answers that said 18 days are now listed as **outdated**, each with its next step.

   From a terminal you can run `python scenarios\kestrel\facts.py --change-leave` instead.

Why it is different: the check compares the answer with the approved value, not with whatever chunk was retrieved. A stale chunk, a missing chunk or a different model gives the same verdict.

### Step 7 (optional): Live RAG with a real LLM
Restart with `-GroqKey gsk_...` (free key from console.groq.com). On the Evaluate page choose
**Generate & evaluate** and ask: *"How many casual leaves do employees get per year, and can
unused leave be carried forward?"* AEGIS retrieves from the PDFs, Groq writes the answer, and
AEGIS judges it. The leave policy and handbook disagree, so expect CAVEAT or ESCALATE.
*Not rehearsed yet: no key was available.*

### Step 8 (optional): Neo4j directly
In the Neo4j Browser:

```cypher
MATCH (n:Document)-[:SUPERSEDES]->(o:Document) RETURN n.source, n.version, o.version;

MATCH (d:Decision)-[:HAS_CLAIM]->(:Claim)-[:CONTRADICTED_BY]->(:Evidence)-[:FROM]->(doc:Document)
RETURN doc.source, count(DISTINCT d) AS decisions ORDER BY decisions DESC;
```

---

## What the dry run measured (honest scorecard)

Each of the 40 replayed interactions has a labelled "correct" outcome in `traffic.py`. AEGIS
matched **30/40**.

* **No wrong answer was let through as ANSWER.** Every invented number, conflict and gap was
  caveated, escalated or abstained.
* **It is over-cautious on correct answers** (the known weakness in `docs/finale/FINAL_REPORT.md`):
  * False CONTRADICTION on 4 correct answers: paternity leave, notice period, parents' insurance
    and USB drives. Answers that start with "No." are often flagged.
  * Correct answers from policies older than 90 days lose score through freshness, even for
    timeless questions (WFH days, maternity cover), so they get CAVEAT instead of ANSWER.
  * Two customer-support cases that should ESCALATE came out ABSTAIN. That is still safe, but
    it isn't routed to a human.
  * Vague questions ("Is it approved?") ABSTAIN on low relevance instead of ESCALATE on ambiguity.
* Wording matters: "Employees **get** 12 days" can score as UNSUPPORTED where "Employees **are
  entitled to** 12 days" is SUPPORTED, and "this year" in a question triggers AMBIGUOUS_QUERY.
