"""Model registry and management for AEGIS Evidence Intelligence."""

from dataclasses import dataclass
from typing import Dict, Optional, List, Any
from enum import Enum
import threading
import logging

logger = logging.getLogger(__name__)


class ModelType(str, Enum):
    """Types of models used in evidence intelligence."""
    EMBEDDING = "embedding"
    NLI = "nli"
    CROSS_ENCODER = "cross_encoder"


@dataclass
class ModelConfig:
    """Configuration for a model."""
    name: str
    model_type: ModelType
    model_id: str  # HuggingFace model ID or local path
    max_length: int = 512
    device: Optional[str] = None  # None = auto-detect
    batch_size: int = 32
    kwargs: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.kwargs is None:
            self.kwargs = {}


# Predefined model candidates for MVP
EMBEDDING_CANDIDATES = [
    ModelConfig(
        name="minilm-l6-v2",
        model_type=ModelType.EMBEDDING,
        model_id="sentence-transformers/all-MiniLM-L6-v2",
        max_length=512,
        batch_size=64,
    ),
]

NLI_CANDIDATES = [
    ModelConfig(
        name="nli-minilm2-l6-h768",
        model_type=ModelType.NLI,
        model_id="cross-encoder/nli-MiniLM2-L6-H768",
        max_length=256,
        batch_size=16,
    ),
]

CROSS_ENCODER_CANDIDATES = [
    ModelConfig(
        name="minilm-l6-v2-ce",
        model_type=ModelType.CROSS_ENCODER,
        model_id="cross-encoder/ms-marco-MiniLM-L-6-v2",
        max_length=512,
        batch_size=32,
    ),
]


class ModelRegistry:
    """Thread-safe model registry with lazy loading and caching."""
    
    _instance: Optional["ModelRegistry"] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._embedding_models: Dict[str, Any] = {}
        self._nli_models: Dict[str, Any] = {}
        self._cross_encoders: Dict[str, Any] = {}
        self._device = self._detect_device()
        self._initialized = True
        logger.info(f"ModelRegistry initialized on device: {self._device}")

    def _detect_device(self) -> str:
        """Detect the best available device (lazy torch import)."""
        try:
            import torch
        except ImportError:
            return "cpu"
        if torch.cuda.is_available():
            return "cuda"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
        return "cpu"

    def get_device(self) -> str:
        """Get the current device."""
        return self._device

    def get_embedding_model(self, config: ModelConfig) -> Any:
        """Get or load an embedding model."""
        from sentence_transformers import SentenceTransformer

        if config.name not in self._embedding_models:
            logger.info(f"Loading embedding model: {config.model_id}")
            model = SentenceTransformer(
                config.model_id,
                device=config.device or self._device,
                **config.kwargs
            )
            model.max_seq_length = config.max_length
            self._embedding_models[config.name] = model
        return self._embedding_models[config.name]

    def get_nli_model(self, config: ModelConfig) -> Any:
        """Get or load an NLI model (returns a pipeline)."""
        if config.name not in self._nli_models:
            logger.info(f"Loading NLI model: {config.model_id}")
            from transformers import pipeline
            pipe = pipeline(
                "text-classification",
                model=config.model_id,
                tokenizer=config.model_id,
                device=0 if (config.device or self._device) == "cuda" else -1,
                top_k=None,
                **config.kwargs
            )
            self._nli_models[config.name] = pipe
        return self._nli_models[config.name]

    def get_cross_encoder(self, config: ModelConfig) -> Any:
        """Get or load a cross-encoder model."""
        from sentence_transformers import CrossEncoder

        if config.name not in self._cross_encoders:
            logger.info(f"Loading cross-encoder: {config.model_id}")
            model = CrossEncoder(
                config.model_id,
                device=config.device or self._device,
                max_length=config.max_length,
                **config.kwargs
            )
            self._cross_encoders[config.name] = model
        return self._cross_encoders[config.name]

    def clear_cache(self):
        """Clear all loaded models (useful for memory management)."""
        self._embedding_models.clear()
        self._nli_models.clear()
        self._cross_encoders.clear()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass


# Singleton instance
model_registry = ModelRegistry()