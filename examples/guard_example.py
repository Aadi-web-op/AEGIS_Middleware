from app.core.evaluator import Evaluator
from app.evidence.registry import default_signals
from app.schemas import Decision, EvaluateRequest

evaluator = Evaluator(default_signals())


def guarded(query: str, answer: str, evidence: list[dict]) -> str:
    """Wrap any RAG answer: show it only if Aegis says it is safe."""
    try:
        result = evaluator.evaluate(
            EvaluateRequest(query=query, answer=answer, evidence=evidence)
        )
    except Exception:
        return "I can't verify this answer right now."  # fail closed

    if result.decision == Decision.ANSWER:
        return answer
    if result.decision == Decision.CAVEAT:
        return f"{answer}\n\nNote: {result.caveat_text}"
    if result.clarifying_question:
        return result.clarifying_question
    return "I can't give a reliable answer to this. A person should check."


if __name__ == "__main__":
    docs = [{"text": "Employees are entitled to 18 casual leaves.",
             "source": "policy_2026.pdf", "date": "2026-08-01", "version": "v3"}]
    print(guarded("How many casual leaves?", "Employees get 18 casual leaves.", docs))
    print(guarded("How many casual leaves?", "Employees get 18 casual leaves.", []))
    