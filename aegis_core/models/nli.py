"""Batched NLI (Natural Language Inference) runner with caching.

Loads a sequence-classification model once per process and runs batched
inference on CPU. Label mapping is derived from the model config, so this works
with any HuggingFace NLI model that exposes entailment/contradiction/neutral
labels, without hardcoding a specific model.
"""

import logging
import threading
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple
from collections import OrderedDict

logger = logging.getLogger(__name__)

# Canonical NLI classes we care about
ENTAILMENT = "entailment"
CONTRADICTION = "contradiction"
NEUTRAL = "neutral"


@dataclass
class NLIPrediction:
    """NLI prediction for a single (premise, hypothesis) pair."""
    entailment: float
    contradiction: float
    neutral: float
    label: str  # "entailment" | "contradiction" | "neutral"

    @property
    def support_score(self) -> float:
        """Net support: entailment minus contradiction, clamped to [0, 1]."""
        return max(0.0, min(1.0, self.entailment - self.contradiction))

    def to_dict(self) -> Dict[str, float]:
        return {
            "entailment": self.entailment,
            "contradiction": self.contradiction,
            "neutral": self.neutral,
            "label": self.label,
        }


class NLIRunner:
    """
    Thread-safe, batched NLI inference with an LRU cache.

    Model loading is lazy and shared. Repeated (premise, hypothesis) pairs are
    served from cache, which matters because the same evidence is checked
    against many claims.
    """

    _instances: Dict[str, "NLIRunner"] = {}
    _lock = threading.Lock()

    def __new__(cls, model_id: str, **kwargs):
        with cls._lock:
            if model_id not in cls._instances:
                instance = super().__new__(cls)
                instance._initialized = False
                cls._instances[model_id] = instance
            return cls._instances[model_id]

    def __init__(
        self,
        model_id: str = "cross-encoder/nli-MiniLM2-L6-H768",
        max_length: int = 256,
        batch_size: int = 16,
        cache_size: int = 2048,
        device: Optional[str] = None,
    ):
        if self._initialized:
            return

        self.model_id = model_id
        self.max_length = max_length
        self.batch_size = batch_size
        self.device = device or self._detect_device()
        self._cache: "OrderedDict[Tuple[str, str], NLIPrediction]" = OrderedDict()
        self._cache_size = cache_size
        self._cache_hits = 0
        self._cache_misses = 0
        self._initialized = True

        self._tokenizer = None
        self._model = None
        self._label_index: Dict[str, int] = {}
        self._torch = None

    @staticmethod
    def _detect_device() -> str:
        try:
            import torch
            if torch.cuda.is_available():
                return "cuda"
        except ImportError:
            pass
        return "cpu"

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        """Load model + tokenizer, derive label index mapping."""
        if self._model is not None:
            return

        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self._torch = torch
        logger.info("Loading NLI model: %s on %s", self.model_id, self.device)

        self._tokenizer = AutoTokenizer.from_pretrained(self.model_id)
        self._model = AutoModelForSequenceClassification.from_pretrained(self.model_id)
        self._model.to(self._torch.device(self.device))
        self._model.eval()

        id2label = self._model.config.id2label
        # Normalize label names -> canonical keys
        for idx, raw_label in id2label.items():
            label = str(raw_label).strip().lower()
            if label.startswith("entail"):
                self._label_index[ENTAILMENT] = int(idx)
            elif label.startswith("contradict"):
                self._label_index[CONTRADICTION] = int(idx)
            elif label.startswith("neutral"):
                self._label_index[NEUTRAL] = int(idx)

        missing = {ENTAILMENT, CONTRADICTION, NEUTRAL} - set(self._label_index)
        if missing:
            raise ValueError(
                f"Model {self.model_id} does not expose required NLI labels. "
                f"Got id2label={id2label}, missing={missing}"
            )

        logger.info(
            "NLI model ready. id2label=%s, mapped=%s", id2label, self._label_index
        )

    def infer_batch(
        self, pairs: List[Tuple[str, str]]
    ) -> List[NLIPrediction]:
        """
        Run NLI on a batch of (premise, hypothesis) pairs.

        Cached pairs are reused; the remainder is run in one batched forward pass.
        """
        if not pairs:
            return []

        self.load()
        torch = self._torch

        results: List[Optional[NLIPrediction]] = [None] * len(pairs)
        to_compute: List[int] = []

        for i, pair in enumerate(pairs):
            cached = self._cache.get(pair)
            if cached is not None:
                self._cache_hits += 1
                self._cache.move_to_end(pair)
                results[i] = cached
            else:
                self._cache_misses += 1
                to_compute.append(i)

        if to_compute:
            premises = [pairs[i][0] for i in to_compute]
            hypotheses = [pairs[i][1] for i in to_compute]

            for start in range(0, len(to_compute), self.batch_size):
                chunk_p = premises[start : start + self.batch_size]
                chunk_h = hypotheses[start : start + self.batch_size]
                idx_chunk = to_compute[start : start + self.batch_size]

                encoded = self._tokenizer(
                    chunk_p,
                    chunk_h,
                    padding=True,
                    truncation=True,
                    max_length=self.max_length,
                    return_tensors="pt",
                ).to(torch.device(self.device))

                with torch.no_grad():
                    logits = self._model(**encoded).logits

                probs = torch.softmax(logits, dim=-1).cpu().numpy()

                for row, orig_idx in enumerate(idx_chunk):
                    ent = float(probs[row][self._label_index[ENTAILMENT]])
                    con = float(probs[row][self._label_index[CONTRADICTION]])
                    neu = float(probs[row][self._label_index[NEUTRAL]])

                    label = max(
                        ((ENTAILMENT, ent), (CONTRADICTION, con), (NEUTRAL, neu)),
                        key=lambda x: x[1],
                    )[0]

                    prediction = NLIPrediction(
                        entailment=ent,
                        contradiction=con,
                        neutral=neu,
                        label=label,
                    )
                    results[orig_idx] = prediction
                    self._cache_store(pairs[orig_idx], prediction)

        return [r for r in results if r is not None]

    def infer(
        self, premise: str, hypothesis: str
    ) -> NLIPrediction:
        """Run NLI on a single (premise, hypothesis) pair."""
        return self.infer_batch([(premise, hypothesis)])[0]

    def _cache_store(self, key: Tuple[str, str], value: NLIPrediction) -> None:
        self._cache[key] = value
        self._cache.move_to_end(key)
        if len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)

    def cache_stats(self) -> Dict[str, Any]:
        total = self._cache_hits + self._cache_misses
        return {
            "hits": self._cache_hits,
            "misses": self._cache_misses,
            "size": len(self._cache),
            "hit_rate": (self._cache_hits / total) if total else 0.0,
        }

    def clear_cache(self) -> None:
        self._cache.clear()
