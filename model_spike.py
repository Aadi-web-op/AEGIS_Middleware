"""Model spike script for evaluating candidate models for AEGIS Evidence Intelligence.

This script evaluates practical CPU-friendly candidates for:
A. embeddings
B. NLI
C. optional cross-encoder

Using ~10 carefully selected test cases covering:
1. direct support
2. paraphrase
3. unrelated evidence
4. contradiction
5. numeric conflict
6. date conflict
7. partial support
8. ambiguous evidence
9. multiple evidence chunks
10. misleading semantically similar evidence
"""

import time
import json
import logging
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Tuple
from pathlib import Path

import torch
import numpy as np
from sentence_transformers import SentenceTransformer, CrossEncoder
from transformers import pipeline

from aegis_core.models.registry import (
    ModelRegistry, ModelConfig, ModelType,
    EMBEDDING_CANDIDATES, NLI_CANDIDATES, CROSS_ENCODER_CANDIDATES
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# ============================================================
# TEST CASES
# ============================================================

@dataclass
class TestCase:
    """A single test case for model evaluation."""
    name: str
    query: str
    answer: str
    evidence: List[str]
    expected_relevance: str  # "high", "medium", "low"
    expected_entailment: str  # "entailment", "contradiction", "neutral"
    description: str


TEST_CASES = [
    TestCase(
        name="1_direct_support",
        query="How many casual leaves can an employee take?",
        answer="Employees receive 18 casual leaves per year.",
        evidence=["Employees are entitled to 18 casual leaves per year."],
        expected_relevance="high",
        expected_entailment="entailment",
        description="Direct support - evidence directly answers query"
    ),
    TestCase(
        name="2_paraphrase",
        query="What is the casual leave policy for employees?",
        answer="Staff members get 18 days of casual leave annually.",
        evidence=["Employees are entitled to 18 casual leaves per year."],
        expected_relevance="high",
        expected_entailment="entailment",
        description="Paraphrase - same meaning, different wording"
    ),
    TestCase(
        name="3_unrelated_evidence",
        query="How many casual leaves can an employee take?",
        answer="Employees receive 18 casual leaves per year.",
        evidence=["The company cafeteria serves lunch from 12 PM to 2 PM."],
        expected_relevance="low",
        expected_entailment="neutral",
        description="Unrelated evidence - completely different topic"
    ),
    TestCase(
        name="4_contradiction",
        query="How many casual leaves can an employee take?",
        answer="Employees receive 18 casual leaves per year.",
        evidence=["Employees are entitled to 12 casual leaves per year."],
        expected_relevance="high",
        expected_entailment="contradiction",
        description="Direct contradiction - different numbers"
    ),
    TestCase(
        name="5_numeric_conflict",
        query="What is the refund period?",
        answer="Customers can request refunds within 30 days.",
        evidence=["Refund requests must be made within 45 days of purchase."],
        expected_relevance="high",
        expected_entailment="contradiction",
        description="Numeric conflict - different time periods"
    ),
    TestCase(
        name="6_date_conflict",
        query="When does the new policy take effect?",
        answer="The policy takes effect on January 1, 2024.",
        evidence=["The updated policy is effective from March 15, 2024."],
        expected_relevance="high",
        expected_entailment="contradiction",
        description="Date conflict - different effective dates"
    ),
    TestCase(
        name="7_partial_support",
        query="What are the leave policies for full-time and part-time employees?",
        answer="Full-time employees get 18 casual leaves. Part-time employees get 10 casual leaves.",
        evidence=["Full-time employees are entitled to 18 casual leaves per year."],
        expected_relevance="medium",
        expected_entailment="entailment",
        description="Partial support - evidence covers only part of answer"
    ),
    TestCase(
        name="8_ambiguous_evidence",
        query="How many casual leaves for senior employees?",
        answer="Senior employees receive 20 casual leaves.",
        evidence=["Employees with more than 5 years tenure receive additional leave benefits."],
        expected_relevance="medium",
        expected_entailment="neutral",
        description="Ambiguous evidence - related but doesn't specify exact number"
    ),
    TestCase(
        name="9_multiple_evidence_chunks",
        query="What is the complete leave policy?",
        answer="Employees get 18 casual leaves, 12 sick leaves, and 10 paid holidays.",
        evidence=[
            "Employees are entitled to 18 casual leaves per year.",
            "Sick leave allowance is 12 days per year.",
            "The company observes 10 paid holidays annually."
        ],
        expected_relevance="high",
        expected_entailment="entailment",
        description="Multiple evidence chunks - all claims supported by different sources"
    ),
    TestCase(
        name="10_misleading_similar",
        query="What is the maternity leave duration?",
        answer="Maternity leave is 26 weeks.",
        evidence=["Paternity leave is 2 weeks for eligible fathers."],
        expected_relevance="medium",  # Semantically similar (leave topic) but wrong type
        expected_entailment="neutral",
        description="Misleading semantically similar - same domain, wrong specific info"
    ),
]


# ============================================================
# EVALUATION FUNCTIONS
# ============================================================

def measure_embedding_model(config: ModelConfig, test_cases: List[TestCase]) -> Dict[str, Any]:
    """Evaluate an embedding model on relevance task."""
    registry = ModelRegistry()
    model = registry.get_embedding_model(config)
    
    results = []
    latencies = []
    
    for tc in test_cases:
        start = time.perf_counter()
        
        # Encode query and evidence
        query_emb = model.encode([tc.query], convert_to_tensor=True, show_progress_bar=False)
        evidence_embs = model.encode(tc.evidence, convert_to_tensor=True, show_progress_bar=False)
        
        # Compute cosine similarities
        from torch.nn.functional import cosine_similarity
        sims = cosine_similarity(query_emb, evidence_embs)
        max_sim = float(sims.max().item()) if len(sims) > 0 else 0.0
        avg_sim = float(sims.mean().item()) if len(sims) > 0 else 0.0
        
        latency = (time.perf_counter() - start) * 1000  # ms
        latencies.append(latency)
        
        results.append({
            "case": tc.name,
            "max_similarity": max_sim,
            "avg_similarity": avg_sim,
            "expected_relevance": tc.expected_relevance,
            "latency_ms": latency,
        })
    
    return {
        "model": config.name,
        "model_id": config.model_id,
        "type": "embedding",
        "avg_latency_ms": np.mean(latencies),
        "std_latency_ms": np.std(latencies),
        "results": results,
    }


def measure_nli_model(config: ModelConfig, test_cases: List[TestCase]) -> Dict[str, Any]:
    """Evaluate an NLI model on entailment task."""
    registry = ModelRegistry()
    pipe = registry.get_nli_model(config)
    
    results = []
    latencies = []
    
    for tc in test_cases:
        start = time.perf_counter()
        
        # For each evidence piece, check entailment with answer
        # NLI: premise=evidence, hypothesis=answer
        entailment_scores = []
        labels = []
        
        for ev in tc.evidence:
            try:
                preds = pipe({"text": ev, "text_pair": tc.answer})
                # Get entailment score (label usually "ENTAILMENT", "CONTRADICTION", "NEUTRAL")
                for p in preds:
                    if p["label"].upper() in ("ENTAILMENT", "CONTRADICTION", "NEUTRAL"):
                        labels.append(p["label"].upper())
                        if p["label"].upper() == "ENTAILMENT":
                            entailment_scores.append(p["score"])
            except Exception as e:
                logger.warning(f"NLI error for {config.name} on {tc.name}: {e}")
                labels.append("ERROR")
        
        latency = (time.perf_counter() - start) * 1000
        latencies.append(latency)
        
        # Determine aggregate label
        if "CONTRADICTION" in labels:
            agg_label = "contradiction"
        elif "ENTAILMENT" in labels:
            agg_label = "entailment"
        elif labels:
            agg_label = "neutral"
        else:
            agg_label = "error"
        
        max_entailment = max(entailment_scores) if entailment_scores else 0.0
        
        results.append({
            "case": tc.name,
            "predicted_label": agg_label,
            "max_entailment_score": max_entailment,
            "all_labels": labels,
            "expected_entailment": tc.expected_entailment,
            "latency_ms": latency,
        })
    
    return {
        "model": config.name,
        "model_id": config.model_id,
        "type": "nli",
        "avg_latency_ms": np.mean(latencies),
        "std_latency_ms": np.std(latencies),
        "results": results,
    }


def measure_cross_encoder(config: ModelConfig, test_cases: List[TestCase]) -> Dict[str, Any]:
    """Evaluate a cross-encoder on relevance/reranking task."""
    registry = ModelRegistry()
    model = registry.get_cross_encoder(config)
    
    results = []
    latencies = []
    
    for tc in test_cases:
        start = time.perf_counter()
        
        # Cross-encoder takes (query, evidence) pairs
        pairs = [(tc.query, ev) for ev in tc.evidence]
        scores = model.predict(pairs, show_progress_bar=False)
        
        max_score = float(np.max(scores)) if len(scores) > 0 else 0.0
        avg_score = float(np.mean(scores)) if len(scores) > 0 else 0.0
        
        latency = (time.perf_counter() - start) * 1000
        latencies.append(latency)
        
        results.append({
            "case": tc.name,
            "max_score": max_score,
            "avg_score": avg_score,
            "expected_relevance": tc.expected_relevance,
            "latency_ms": latency,
        })
    
    return {
        "model": config.name,
        "model_id": config.model_id,
        "type": "cross_encoder",
        "avg_latency_ms": np.mean(latencies),
        "std_latency_ms": np.std(latencies),
        "results": results,
    }


def get_model_size(config: ModelConfig) -> Dict[str, Any]:
    """Estimate model size."""
    registry = ModelRegistry()
    try:
        if config.model_type == ModelType.EMBEDDING:
            model = registry.get_embedding_model(config)
            # Count parameters
            total_params = sum(p.numel() for p in model.parameters())
        elif config.model_type == ModelType.CROSS_ENCODER:
            model = registry.get_cross_encoder(config)
            total_params = sum(p.numel() for p in model.model.parameters())
        else:
            # NLI model - harder to get size without loading fully
            total_params = 0
        
        size_mb = total_params * 4 / (1024 * 1024)  # fp32 approx
        return {"param_count": total_params, "size_mb_fp32": size_mb}
    except Exception as e:
        logger.warning(f"Could not measure size for {config.name}: {e}")
        return {"param_count": 0, "size_mb_fp32": 0}


def run_model_spike():
    """Run the complete model spike evaluation."""
    logger.info("=" * 60)
    logger.info("AEGIS MODEL SPIKE EVALUATION")
    logger.info("=" * 60)
    
    device = ModelRegistry().get_device()
    logger.info(f"Running on device: {device}")
    logger.info(f"PyTorch version: {torch.__version__}")
    logger.info(f"Test cases: {len(TEST_CASES)}")
    
    all_results = {
        "metadata": {
            "device": device,
            "torch_version": torch.__version__,
            "num_test_cases": len(TEST_CASES),
            "test_cases": [tc.name for tc in TEST_CASES],
        },
        "embeddings": [],
        "nli": [],
        "cross_encoders": [],
    }
    
    # Evaluate embedding models
    logger.info("\n--- Evaluating Embedding Models ---")
    for config in EMBEDDING_CANDIDATES:
        logger.info(f"Testing {config.name} ({config.model_id})...")
        size_info = get_model_size(config)
        result = measure_embedding_model(config, TEST_CASES)
        result.update(size_info)
        all_results["embeddings"].append(result)
        logger.info(f"  Avg latency: {result['avg_latency_ms']:.1f}ms, Size: {size_info.get('size_mb_fp32', 0):.1f}MB")
    
    # Evaluate NLI models
    logger.info("\n--- Evaluating NLI Models ---")
    for config in NLI_CANDIDATES:
        logger.info(f"Testing {config.name} ({config.model_id})...")
        size_info = get_model_size(config)
        result = measure_nli_model(config, TEST_CASES)
        result.update(size_info)
        all_results["nli"].append(result)
        logger.info(f"  Avg latency: {result['avg_latency_ms']:.1f}ms")
    
    # Evaluate Cross-Encoder models
    logger.info("\n--- Evaluating Cross-Encoder Models ---")
    for config in CROSS_ENCODER_CANDIDATES:
        logger.info(f"Testing {config.name} ({config.model_id})...")
        size_info = get_model_size(config)
        result = measure_cross_encoder(config, TEST_CASES)
        result.update(size_info)
        all_results["cross_encoders"].append(result)
        logger.info(f"  Avg latency: {result['avg_latency_ms']:.1f}ms, Size: {size_info.get('size_mb_fp32', 0):.1f}MB")
    
    # Save results
    output_path = Path("model_spike_results.json")
    with open(output_path, "w") as f:
        json.dump(all_results, f, indent=2)
    
    logger.info(f"\nResults saved to {output_path}")
    
    # Print summary
    print("\n" + "=" * 60)
    print("MODEL SPIKE SUMMARY")
    print("=" * 60)
    
    for category in ["embeddings", "nli", "cross_encoders"]:
        print(f"\n{category.upper()}:")
        for r in all_results[category]:
            print(f"  {r['model']}: {r['avg_latency_ms']:.1f}ms avg, "
                  f"{r.get('size_mb_fp32', 0):.1f}MB, "
                  f"{r.get('param_count', 0)/1e6:.1f}M params")
    
    return all_results


if __name__ == "__main__":
    run_model_spike()