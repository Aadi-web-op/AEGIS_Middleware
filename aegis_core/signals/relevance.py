"""Relevance Signal - Determines whether retrieved evidence is related to the query."""

import logging
from typing import List, Dict, Any, Optional
import numpy as np
import torch
from torch.nn.functional import cosine_similarity

from aegis_core.signals.base import BaseSignal, SignalResult, SignalName
from aegis_core.models.registry import model_registry, ModelConfig, ModelType, EMBEDDING_CANDIDATES, CROSS_ENCODER_CANDIDATES

logger = logging.getLogger(__name__)


class RelevanceSignal(BaseSignal):
    """
    Relevance signal using sentence embeddings with optional cross-encoder reranking.
    
    Computes semantic similarity between query and evidence passages.
    Returns a score in [0, 1] where higher means more relevant.
    """
    
    def __init__(
        self,
        embedding_config: Optional[ModelConfig] = None,
        cross_encoder_config: Optional[ModelConfig] = None,
        use_cross_encoder: bool = False,
        top_k: int = 5,
        similarity_threshold: float = 0.3,
    ):
        """
        Initialize the relevance signal.
        
        Args:
            embedding_config: Embedding model configuration (uses default if None)
            cross_encoder_config: Cross-encoder config for reranking (optional)
            use_cross_encoder: Whether to use cross-encoder for reranking
            top_k: Maximum number of evidence passages to consider
            similarity_threshold: Minimum similarity to consider evidence relevant
        """
        self.embedding_config = embedding_config or EMBEDDING_CANDIDATES[0]
        self.cross_encoder_config = cross_encoder_config or CROSS_ENCODER_CANDIDATES[0]
        self.use_cross_encoder = use_cross_encoder
        self.top_k = top_k
        self.similarity_threshold = similarity_threshold
        
        self._embedding_model = None
        self._cross_encoder = None
    
    @property
    def signal_name(self) -> SignalName:
        return SignalName.RELEVANCE
    
    @property
    def embedding_model(self):
        """Lazy load embedding model."""
        if self._embedding_model is None:
            self._embedding_model = model_registry.get_embedding_model(self.embedding_config)
        return self._embedding_model
    
    @property
    def cross_encoder(self):
        """Lazy load cross-encoder if enabled."""
        if self.use_cross_encoder and self._cross_encoder is None:
            self._cross_encoder = model_registry.get_cross_encoder(self.cross_encoder_config)
        return self._cross_encoder
    
    def evaluate(
        self,
        query: str,
        answer: str,
        evidence: List[str],
        **kwargs
    ) -> SignalResult:
        """
        Evaluate relevance of evidence to query.
        
        Args:
            query: User's query
            answer: AI system's answer (not used for relevance, but kept for interface consistency)
            evidence: List of retrieved evidence passages
            **kwargs: Additional parameters (e.g., evidence_metadata)
            
        Returns:
            SignalResult with relevance score, reasons, and diagnostic details
        """
        # Handle edge cases
        if not evidence:
            return self._handle_empty_evidence(SignalName.RELEVANCE, default_value=0.0)
        
        if not query or not query.strip():
            return SignalResult(
                signal=SignalName.RELEVANCE,
                value=0.0,
                reasons=["Empty query provided"],
                details={"query_length": 0, "evidence_count": len(evidence)}
            )
        
        # Limit evidence to top_k
        evidence_to_process = evidence[:self.top_k]
        
        # Compute embeddings
        try:
            query_emb = self.embedding_model.encode(
                [query], 
                convert_to_tensor=True, 
                show_progress_bar=False
            )
            evidence_embs = self.embedding_model.encode(
                evidence_to_process, 
                convert_to_tensor=True, 
                show_progress_bar=False
            )
        except Exception as e:
            logger.error(f"Embedding computation failed: {e}")
            return SignalResult(
                signal=SignalName.RELEVANCE,
                value=0.0,
                reasons=[f"Embedding computation failed: {str(e)}"],
                details={"error": str(e), "evidence_count": len(evidence_to_process)}
            )
        
        # Compute cosine similarities
        sims = cosine_similarity(query_emb, evidence_embs)
        sims_np = sims.cpu().numpy().flatten()
        
        # Get statistics
        max_sim = float(np.max(sims_np)) if len(sims_np) > 0 else 0.0
        avg_sim = float(np.mean(sims_np)) if len(sims_np) > 0 else 0.0
        min_sim = float(np.min(sims_np)) if len(sims_np) > 0 else 0.0
        
        # Count evidence above threshold
        relevant_count = int(np.sum(sims_np >= self.similarity_threshold))
        
        # Optional cross-encoder reranking for top candidates
        ce_scores = None
        if self.use_cross_encoder and self.cross_encoder is not None:
            try:
                pairs = [(query, ev) for ev in evidence_to_process]
                ce_scores = self.cross_encoder.predict(pairs, show_progress_bar=False)
                ce_scores = [float(s) for s in ce_scores]
                max_sim = max(max_sim, max(ce_scores)) if ce_scores else max_sim
            except Exception as e:
                logger.warning(f"Cross-encoder reranking failed: {e}")
        
        # Normalize score to [0, 1] using sigmoid-like scaling
        # This maps raw cosine similarity (typically 0.2-0.8 for relevant) to 0-1
        normalized_score = self._normalize_score(max_sim)
        
        # Generate reasons
        reasons = self._generate_reasons(
            max_sim, avg_sim, min_sim, relevant_count, 
            len(evidence_to_process), ce_scores
        )
        
        # Build details
        details = {
            "max_similarity": max_sim,
            "avg_similarity": avg_sim,
            "min_similarity": min_sim,
            "relevant_count": relevant_count,
            "total_evidence_count": len(evidence_to_process),
            "similarity_threshold": self.similarity_threshold,
            "per_evidence_similarities": sims_np.tolist(),
            "embedding_model": self.embedding_config.name,
        }
        
        if ce_scores is not None:
            details["cross_encoder_scores"] = ce_scores
            details["cross_encoder_model"] = self.cross_encoder_config.name
        
        if len(evidence) > self.top_k:
            details["truncated"] = True
            details["original_evidence_count"] = len(evidence)
        
        return SignalResult(
            signal=SignalName.RELEVANCE,
            value=normalized_score,
            reasons=reasons,
            details=details
        )
    
    def _normalize_score(self, raw_similarity: float) -> float:
        """
        Normalize cosine similarity to [0, 1] relevance score.
        
        Cosine similarity for relevant pairs typically ranges 0.4-0.8.
        We use a piecewise linear mapping:
        - < 0.2 -> 0.0 (unrelated)
        - 0.2-0.4 -> 0.0-0.3 (weakly related)
        - 0.4-0.6 -> 0.3-0.7 (moderately related)
        - 0.6-0.8 -> 0.7-0.9 (strongly related)
        - > 0.8 -> 0.9-1.0 (very strongly related)
        """
        if raw_similarity <= 0.2:
            return 0.0
        elif raw_similarity <= 0.4:
            return (raw_similarity - 0.2) * 1.5  # 0.0 to 0.3
        elif raw_similarity <= 0.6:
            return 0.3 + (raw_similarity - 0.4) * 2.0  # 0.3 to 0.7
        elif raw_similarity <= 0.8:
            return 0.7 + (raw_similarity - 0.6) * 1.0  # 0.7 to 0.9
        else:
            return min(0.9 + (raw_similarity - 0.8) * 0.5, 1.0)  # 0.9 to 1.0
    
    def _generate_reasons(
        self,
        max_sim: float,
        avg_sim: float,
        min_sim: float,
        relevant_count: int,
        total_count: int,
        ce_scores: Optional[List[float]]
    ) -> List[str]:
        """Generate human-readable reasons for the relevance score."""
        reasons = []
        
        if total_count == 0:
            reasons.append("No evidence provided")
            return reasons
        
        if max_sim >= 0.7:
            reasons.append(f"Strong semantic match found (max similarity: {max_sim:.2f})")
        elif max_sim >= 0.5:
            reasons.append(f"Moderate semantic match (max similarity: {max_sim:.2f})")
        elif max_sim >= 0.3:
            reasons.append(f"Weak semantic match (max similarity: {max_sim:.2f})")
        else:
            reasons.append(f"Low semantic relevance (max similarity: {max_sim:.2f})")
        
        if relevant_count == total_count:
            reasons.append(f"All {total_count} evidence passages are relevant")
        elif relevant_count > 0:
            reasons.append(f"{relevant_count}/{total_count} evidence passages exceed relevance threshold")
        else:
            reasons.append("No evidence passages exceed relevance threshold")
        
        if ce_scores:
            max_ce = max(ce_scores)
            if max_ce > 0.7:
                reasons.append(f"Cross-encoder confirms strong relevance (score: {max_ce:.2f})")
            elif max_ce > 0.5:
                reasons.append(f"Cross-encoder shows moderate relevance (score: {max_ce:.2f})")
        
        if avg_sim < 0.3 and max_sim < 0.5:
            reasons.append("Evidence appears largely unrelated to query")
        
        return reasons


def create_relevance_signal(**kwargs) -> RelevanceSignal:
    """Factory function to create a RelevanceSignal with default config."""
    return RelevanceSignal(**kwargs)