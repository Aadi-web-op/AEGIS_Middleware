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
