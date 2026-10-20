
import logging
from datetime import date

from app.providers.base import LLMProvider
from app.schemas import Decision, EvaluateRequest, EvidenceItem, RecommendedAction
from app.core.evaluator import Evaluator
from app.rag.knowledge_base import KnowledgeBase

logger = logging.getLogger(__name__)


class AEGISWorkflow:
    """Connect baseline RAG answers to the existing AEGIS evaluator."""

    def __init__(
        self,
        knowledge_base: KnowledgeBase,
        provider: LLMProvider,
        evaluator: Evaluator,
        audit_logger=None,
        escalation_queue=None,
    ):
        self.knowledge_base = knowledge_base
        self.provider = provider
        self.evaluator = evaluator
        self.audit_logger = audit_logger
        self.escalation_queue = escalation_queue

    @staticmethod
    def _to_evidence_item(chunk) -> EvidenceItem:
        """Preserve source, date and version from each retrieved chunk."""

        document_date = None

        if chunk.date:
            if isinstance(chunk.date, date):
                document_date = chunk.date
            else:
                try:
                    document_date = date.fromisoformat(str(chunk.date))
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
            empty_req = EvaluateRequest(
                query=question,
                answer="No answer generated: no evidence is available.",
                evidence=[],
                profile=profile,
                time_sensitive=time_sensitive,
            )
            empty_res = self.evaluator.evaluate(empty_req)
            if self.audit_logger is not None:
                self.audit_logger.log_evaluation(empty_req, empty_res, generation_success=None)
            if self.escalation_queue is not None and (
                empty_res.decision == Decision.ESCALATE
                or empty_res.recommended_action == RecommendedAction.ESCALATE_TO_HUMAN
            ):
                reason_msg = "; ".join(r.message for r in empty_res.reasons) if empty_res.reasons else "Evaluator escalated case to human review."
                try:
                    self.escalation_queue.enqueue(
                        request_id=empty_res.request_id,
                        reason=reason_msg,
                        decision=empty_res.decision.value,
                        query=empty_req.query,
                        answer=empty_req.answer,
                        notes=f"Auto-escalated from RAG workflow. Action: {empty_res.recommended_action.value}",
                        raise_on_duplicate=False,
                    )
                except Exception as exc:
                    logger.warning("Failed to auto-enqueue escalation in workflow: %s", exc)
            return empty_res

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
        response = self.evaluator.evaluate(request)
        if self.audit_logger is not None:
            self.audit_logger.log_evaluation(request, response, generation_success=True)

        if self.escalation_queue is not None and (
            response.decision == Decision.ESCALATE
            or response.recommended_action == RecommendedAction.ESCALATE_TO_HUMAN
        ):
            reason_msg = "; ".join(r.message for r in response.reasons) if response.reasons else "Evaluator escalated case to human review."
            try:
                self.escalation_queue.enqueue(
                    request_id=response.request_id,
                    reason=reason_msg,
                    decision=response.decision.value,
                    query=request.query,
                    answer=request.answer,
                    notes=f"Auto-escalated from RAG workflow. Action: {response.recommended_action.value}",
                    raise_on_duplicate=False,
                )
            except Exception as exc:
                logger.warning("Failed to auto-enqueue escalation in workflow: %s", exc)
        return response
