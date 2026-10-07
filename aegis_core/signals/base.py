"""Shared signal interface for AEGIS Evidence Intelligence Engine."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum


class SignalName(str, Enum):
    """Names of the evidence intelligence signals."""
    RELEVANCE = "relevance"
    ENTAILMENT = "entailment"
    CONTRADICTION = "contradiction"
    COMPLETENESS = "completeness"
    FRESHNESS = "freshness"
    AMBIGUITY = "ambiguity"


@dataclass
class SignalResult:
    """Standardized result structure for all evidence signals."""
    signal: SignalName
    value: float  # 0.0 to 1.0
    reasons: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Validate value is in range [0, 1]."""
        if not 0.0 <= self.value <= 1.0:
            raise ValueError(f"Signal value must be in [0, 1], got {self.value}")


class BaseSignal(ABC):
    """Abstract base class for all evidence intelligence signals."""
    
    @property
    @abstractmethod
    def signal_name(self) -> SignalName:
        """Return the signal name this implementation handles."""
        pass
    
    @abstractmethod
    def evaluate(
        self,
        query: str,
        answer: str,
        evidence: List[str],
        **kwargs
    ) -> SignalResult:
        """
        Evaluate the signal for the given query, answer, and evidence.
        
        Args:
            query: The user's original query
            answer: The AI system's answer
            evidence: List of retrieved evidence passages
            **kwargs: Additional signal-specific parameters
            
        Returns:
            SignalResult with score, reasons, and diagnostic details
        """
        pass
    
    def _handle_empty_evidence(self, signal: SignalName, default_value: float = 0.0) -> SignalResult:
        """Handle case where evidence is empty or missing."""
        return SignalResult(
            signal=signal,
            value=default_value,
            reasons=["No evidence provided for evaluation"],
            details={"evidence_count": 0}
        )
    
    def _handle_empty_answer(self, signal: SignalName, default_value: float = 0.0) -> SignalResult:
        """Handle case where answer is empty or missing."""
        return SignalResult(
            signal=signal,
            value=default_value,
            reasons=["No answer provided for evaluation"],
            details={"answer_length": 0}
        )