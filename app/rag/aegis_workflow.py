
from datetime import date

from app.providers.base import LLMProvider
from app.schemas import EvaluateRequest, EvidenceItem
from app.core.evaluator import Evaluator
from app.rag.knowledge_base import KnowledgeBase


class AEGISWorkflow:
    """Connect baseline RAG answers to the existing AEGIS evaluator."""

    def __init__(
        self,
        knowledge_base: KnowledgeBase,
        provider: LLMProvider,
        evaluator: Evaluator,
    ):
        self.knowledge_base = knowledge_base
        self.provider = provider
        self.evaluator = evaluator

    @staticmethod
    def _to_evidence_item(chunk) -> EvidenceItem:
        """Preserve source, date and version from each retrieved chunk."""

        document_date = None

        if chunk.date:
            try:
                document_date = date.fromisoformat(chunk.date)
            except (ValueError, TypeError):
                document_date = None

        return EvidenceItem(
            text=chunk.text,
            source=chunk.source,
            date=document_date,
            version=chunk.version,
        )

    def run(
        self,
        question: str,
        top_k: int = 5,
        profile: str = "standard",
        time_sensitive: bool = True,
    ):
        """Retrieve evidence, generate a baseline answer and evaluate it."""

        if not question.strip():
            raise ValueError("Question cannot be empty.")

        # Do not call an LLM when the knowledge base has no evidence.
        if self.knowledge_base.vector_store.index.ntotal == 0:
            return self.evaluator.evaluate(
                EvaluateRequest(
                    query=question,
                    answer="No answer generated: no evidence is available.",
                    evidence=[],
                    profile=profile,
                    time_sensitive=time_sensitive,
                )
            )

        # Retrieve evidence and generate the baseline RAG answer.
        rag_answer = self.knowledge_base.answer(
            question,
            provider=self.provider,
            top_k=top_k,
        )

        evidence_items = [
            self._to_evidence_item(chunk)
            for chunk in rag_answer.evidence
        ]

        request = EvaluateRequest(
            query=question,
            answer=rag_answer.answer,
            evidence=evidence_items,
            profile=profile,
            time_sensitive=time_sensitive,
        )

        # Use the team's existing evaluator and signals.
        return self.evaluator.evaluate(request)
