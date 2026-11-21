# Contributing to Aegis Middleware

Thank you for your interest in contributing to **Aegis**! Aegis is an open-source, model-agnostic uncertainty middleware designed to evaluate whether AI answers are supported by available evidence before they reach users.

---

## 1. Development & Git Workflow

We adhere to standard open-source collaboration practices:
* **Main Branch:** `main` is always stable and demo-ready. Direct pushes to `main` are restricted.
* **Feature Branches:** Create short-lived branches prefixed by feature or fix, e.g., `feature/custom-signal-name` or `fix/relevance-scoring`.
* **Testing:** Every PR must include unit/integration tests and all tests must pass (`pytest`) before merge.
* **Clean Secrets:** Never commit API keys, tokens, or local credentials. Copy `.env.example` to `.env` for local keys.

---

## 2. Environment Setup

```bash
# 1. Clone repository
git clone https://github.com/your-org/AEGIS_Middleware.git
cd AEGIS_Middleware

# 2. Create virtual environment
python -m venv .venv
# On Windows:
.\.venv\Scripts\Activate.ps1
# On Linux/macOS:
source .venv/bin/activate

# 3. Install in editable mode with development dependencies
pip install -e .
pip install -r requirements.txt

# 4. Run tests
pytest tests/
```

---

## 3. How to Add Your Own Signal (Plugin Architecture)

Aegis is designed to be easily extensible. Every uncertainty signal implements the `Signal` interface from `app.evidence.base` and returns a typed `SignalResult`:

```python
from app.evidence.base import Signal
from app.schemas import EvidenceItem, Reason, ReasonCode, SignalResult

class SourceAuthoritySignal(Signal):
    """Measures source document trustworthiness (e.g., official PDF > email > forum)."""

    name = "source_authority"  # Unique identifier for the signal

    def score(
        self,
        query: str,
        answer: str,
        evidence: list[EvidenceItem],
    ) -> SignalResult:
        if not evidence:
            return SignalResult(
                value=0.0,
                reasons=[Reason(code=ReasonCode.NO_EVIDENCE, message="No evidence available.")],
                details={"authority_level": "none"}
            )

        # Compute authority metric in [0.0, 1.0]
        authority_weights = {".gov": 1.0, ".edu": 0.9, ".org": 0.8, "default": 0.5}
        scores = []
        for item in evidence:
            src = item.source or ""
            w = next((v for k, v in authority_weights.items() if k in src), authority_weights["default"])
            scores.append(w)

        avg_score = sum(scores) / len(scores)

        reasons = []
        if avg_score < 0.6:
            reasons.append(Reason(
                code=ReasonCode.LOW_RELEVANCE,
                message="Retrieved sources have low official authority."
            ))

        return SignalResult(
            value=round(avg_score, 4),
            reasons=reasons,
            details={"scores": scores, "avg_authority": avg_score}
        )
```

### Registering Your Signal

Add your signal to `default_signals()` in `app/evidence/registry.py`:

```python
from app.evidence.registry import default_signals

def custom_signals():
    return [
        *default_signals(),
        SourceAuthoritySignal(),
    ]
```

Or configure custom weights and thresholds in `config/policy.yaml`.

---

## 4. Code Standards & Pull Requests

* Type hints (`from typing import ...`, Pydantic models) are encouraged on all public interfaces.
* Follow PEP 8 guidelines.
* Every PR should state:
  1. What was changed.
  2. Why it was changed.
  3. How it was tested.
