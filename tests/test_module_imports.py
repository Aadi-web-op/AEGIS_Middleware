"""Import every first-party module so module-level errors cannot hide.

A missing `typing` import inside a function *annotation* (evaluated at class
body execution time) broke collection of 11 test files on main. Modules that
no test happens to import can carry the same defect silently, so this test
imports the whole `app` and `aegis_core` trees and fails on the first module
that cannot be imported.
"""

import importlib
import pkgutil

import pytest

import aegis_core
import app

# Modules that intentionally need optional runtime state (a live Neo4j
# driver, a configured provider key, ...) must still *import* cleanly;
# nothing is exempt. Add an entry here only with a recorded reason.
SKIP: dict[str, str] = {}


def _module_names():
    names = []
    for package in (app, aegis_core):
        names.append(package.__name__)
        for info in pkgutil.walk_packages(package.__path__, package.__name__ + "."):
            names.append(info.name)
    return sorted(names)


MODULES = _module_names()


def test_module_tree_is_discoverable():
    """Guard the guard: a broken walk would make this file vacuously pass."""
    assert len(MODULES) > 30, MODULES
    assert "app.core.evaluator" in MODULES
    assert "aegis_core.evidence.engine" in MODULES


@pytest.mark.parametrize("name", MODULES)
def test_module_imports(name):
    if name in SKIP:
        pytest.skip(SKIP[name])
    importlib.import_module(name)
