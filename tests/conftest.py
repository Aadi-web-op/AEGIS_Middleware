"""Shared fixtures and config for the AEGIS test suite."""

import os

# Do NOT override HF_HOME: the spike already populated the user's
# default HuggingFace cache, so tests reuse those downloads instead
# of re-fetching every model into a cold directory.
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def evidence_engine():
    """Build a real EvidenceEngine; models load lazily on first use."""
    from aegis_core import EvidenceEngine
    engine = EvidenceEngine()
    # Warm up so individual tests measure inference, not load time.
    engine.evaluate(
        query="warm up",
        answer="warm up the models",
        evidence=["warm up the models for the test session"],
    )
    return engine


class FakeNLI:
    """A deterministic stand-in for `NLIRunner`.

    Signal tests need exact entailment/contradiction probabilities to
    assert on claim-level indices, which a real model cannot give. Pairs
    not in `table` fall back to `default`, so a test only states the
    pairs it cares about.
    """

    model_id = "fake/nli"

    def __init__(self, table=None, default=(0.10, 0.10, 0.80)):
        from aegis_core.models.nli import NLIPrediction

        self._prediction = NLIPrediction
        self.table = dict(table or {})
        self.default = default
        self.batches = []

    def infer_batch(self, pairs):
        self.batches.append(list(pairs))
        out = []
        for premise, hypothesis in pairs:
            ent, con, neu = self.table.get((premise, hypothesis), self.default)
            label = max(
                (("entailment", ent), ("contradiction", con), ("neutral", neu)),
                key=lambda item: item[1],
            )[0]
            out.append(
                self._prediction(
                    entailment=ent, contradiction=con, neutral=neu, label=label
                )
            )
        return out


class BrokenNLI:
    """An NLI runner that always fails, for the degraded-model paths."""

    model_id = "broken/nli"

    def infer_batch(self, pairs):
        raise RuntimeError("NLI model unavailable")


@pytest.fixture
def fake_nli():
    """Factory: `fake_nli({(premise, hypothesis): (ent, con, neu)})`."""
    return FakeNLI
