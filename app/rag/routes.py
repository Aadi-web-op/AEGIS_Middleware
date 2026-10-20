from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.providers.base import ProviderError
from app.providers.factory import build_provider
from app.rag.aegis_workflow import AEGISWorkflow
from app.rag.knowledge_base import KnowledgeBase
from app.schemas import EvaluateResponse

router = APIRouter(prefix="/v1/rag", tags=["RAG"])


class IngestPDFRequest(BaseModel):
    pdf_path: str
    date: str | None = None
    version: str | None = None


class RAGAskRequest(BaseModel):
    question: str
    top_k: int = Field(default=5, ge=1, le=20)
    profile: str = "standard"
    time_sensitive: bool = True


@router.post("/ingest")
def ingest_pdf(payload: IngestPDFRequest, request: Request):
    try:
        kb = getattr(request.app.state, "rag_knowledge_base", None)
        if kb is None:
            kb = KnowledgeBase()
            request.app.state.rag_knowledge_base = kb

        chunks_added = kb.ingest_pdf(
            pdf_path=payload.pdf_path,
            date=payload.date,
            version=payload.version,
        )
        return {
            "status": "ok",
            "pdf_path": payload.pdf_path,
            "chunks_added": chunks_added,
            "message": "PDF ingested successfully.",
        }
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/ask", response_model=EvaluateResponse)
def ask_rag(payload: RAGAskRequest, request: Request):
    if not payload.question.strip():
        raise HTTPException(status_code=422, detail="Question cannot be empty.")

    kb = getattr(request.app.state, "rag_knowledge_base", None)
    if kb is None or kb.vector_store.index.ntotal == 0:
        raise HTTPException(
            status_code=409,
            detail="Knowledge base is empty. Ingest a PDF first.",
        )

    try:
        provider = getattr(request.app.state, "rag_provider", None)
        if provider is None:
            provider = build_provider()
            request.app.state.rag_provider = provider

        workflow = AEGISWorkflow(
            knowledge_base=kb,
            provider=provider,
            evaluator=request.app.state.evaluator,
        )
        return workflow.run(
            question=payload.question,
            top_k=payload.top_k,
            profile=payload.profile,
            time_sensitive=payload.time_sensitive,
        )
    except ProviderError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"LLM provider unavailable: {exc}",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
