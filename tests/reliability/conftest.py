"""Fixtures for the reliability suite.

Two kinds of test live here:

* fast, deterministic tests that drive the policy / evaluator / adapter with
  stub signals or a fake NLI runner -- no model is loaded;
* tests marked ``real_models`` that run the live signal stack (embedding +
  NLI models from the local HuggingFace cache). Deselect them with
  ``-m "not real_models"``.
"""

import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "real_models: runs the real embedding and NLI models (slower, needs the model cache)",
    )


@pytest.fixture(scope="session")
def live_evaluator():
    from app.core.evaluator import Evaluator
    from app.evidence.registry import default_signals

    return Evaluator(default_signals())
