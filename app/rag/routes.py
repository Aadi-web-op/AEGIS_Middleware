import logging
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import APIRouter, Body, HTTPException, Query, Request
from pydantic import BaseModel, Field
from pypdf.errors import PdfReadError

from app.graph.document_versions import register_document
from app.providers.base import ProviderError
from app.providers.factory import build_provider
from app.rag.aegis_workflow import AEGISWorkflow
from app.rag.knowledge_base import KnowledgeBase
from app.schemas import EvaluateResponse

router = APIRouter(prefix="/v1/rag", tags=["RAG"])
logger = logging.getLogger(__name__)


class IngestPDFRequest(BaseModel):
    pdf_path: str
    date: str | None = None
    version: str | None = None
    source: str | None = Field(default=None, min_length=1)


class RAGAskRequest(BaseModel):
    question: str
    top_k: int = Field(default=5, ge=1, le=20)
    profile: str = "standard"
    time_sensitive: bool = True


def _ingest_pdf(payload: IngestPDFRequest, request: Request):
    try:
        state = request.app.state
        with state.rag_ingestion_lock:
            kb = getattr(state, "rag_knowledge_base", None)
            if kb is None:
                kb = KnowledgeBase()
                state.rag_knowledge_base = kb

            revision, chunks_added = kb.ingest_document(
                pdf_path=payload.pdf_path,
                date=payload.date,
                version=payload.version,
                source=payload.source,
            )
            change = {"status": "unavailable"}
            if state.neo4j_driver is not None:
                try:
                    change = register_document(state.neo4j_driver, revision)
                except Exception:
                    logger.exception("Could not register document revision %s", revision.id)

        return {
            "status": "ok",
            "chunks_added": chunks_added,
            "message": "PDF ingested successfully.",
            "document": {
                "id": revision.id,
                "source": revision.source,
                "version": revision.version,
                "content_hash": revision.content_hash,
            },
            "change_detection": change,
        }
    except (FileNotFoundError, PdfReadError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/ingest")
def ingest_pdf(payload: IngestPDFRequest, request: Request):
    return {"pdf_path": payload.pdf_path, **_ingest_pdf(payload, request)}


@router.post("/ingest/upload")
def upload_pdf(
    request: Request,
    pdf: bytes = Body(media_type="application/pdf"),
    source: str = Query(min_length=1),
    version: str | None = None,
    date: str | None = None,
):
    with TemporaryDirectory() as directory:
        path = Path(directory) / "document.pdf"
        path.write_bytes(pdf)
        return _ingest_pdf(
            IngestPDFRequest(pdf_path=str(path), source=source, version=version, date=date),
            request,
        )


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

    audit_logger = getattr(request.app.state, "audit_logger", None)
    try:
        provider = getattr(request.app.state, "rag_provider", None)
        if provider is None:
            provider = build_provider()
            request.app.state.rag_provider = provider

        workflow = AEGISWorkflow(
            knowledge_base=kb,
            provider=provider,
            evaluator=request.app.state.evaluator,
            audit_logger=audit_logger,
            escalation_queue=getattr(request.app.state, "escalation_queue", None),
            finish_evaluation=request.app.state.finish_evaluation,
        )
        return workflow.run(
            question=payload.question,
            top_k=payload.top_k,
            profile=payload.profile,
            time_sensitive=payload.time_sensitive,
        )
    except ProviderError as exc:
        if audit_logger is not None:
            audit_logger.log_generation_failure(
                query=payload.question,
                error=str(exc),
                profile=payload.profile,
            )
        raise HTTPException(
            status_code=503,
            detail=f"LLM provider unavailable: {exc}",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
