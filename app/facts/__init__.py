"""Fact Lock: approved, versioned facts that every AI answer is checked against."""

from app.facts.graph import FactGraph
from app.facts.lock import FactLock, FactLockResult
from app.facts.routes import router as facts_router
from app.facts.store import LEVELS, Fact, FactStore

__all__ = ["Fact", "FactGraph", "FactLock", "FactLockResult", "FactStore", "LEVELS", "facts_router"]
