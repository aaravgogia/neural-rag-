import logging
import os
import tempfile
import uuid
import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.auth import get_current_user
from app.core.document_processor import DocumentProcessor
from app.core.ingestion import enqueue_ingestion
from app.core.security import validate_namespace
from app.core.workspaces import require_workspace_role
from app.models.database import Document, DocumentRedaction, User, get_db
from app.models.schemas import DocumentResponse

router = APIRouter(prefix="/documents", tags=["Documents"])
logger = logging.getLogger(__name__)
UPLOAD_DIR = Path("./uploads")
ALLOWED_TYPES = {".pdf", ".docx", ".txt", ".html"}
COPY_CHUNK_SIZE = 1024 * 1024


def safe_filename(filename: str | None) -> tuple[str, str]:
    # Normalise both Windows and POSIX separators before using the supplied name
    # only as display metadata. A generated temp path holds the real upload.
    name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    suffix = Path(name).suffix.lower()
    if not name or name in {".", ".."} or suffix not in ALLOWED_TYPES:
        raise HTTPException(400, "Only PDF, DOCX, TXT, and HTML files are supported")
    return name[:255], suffix


async def write_limited_upload(file: UploadFile, suffix: str, max_bytes: int) -> tuple[str, int]:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    size = 0
    with tempfile.NamedTemporaryFile("wb", delete=False, dir=UPLOAD_DIR, prefix="upload-", suffix=suffix) as target:
        path = target.name
        while chunk := await file.read(COPY_CHUNK_SIZE):
            size += len(chunk)
            if size > max_bytes:
                target.close()
                os.unlink(path)
                raise HTTPException(413, f"File exceeds the {max_bytes // (1024 * 1024)} MB limit")
            target.write(chunk)
    return path, size


@router.get("", response_model=list[DocumentResponse])
async def list_documents(workspace_id: str = Query(...), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require_workspace_role(db, workspace_id, current_user.id)
    result = await db.execute(select(Document).where(Document.workspace_id == workspace_id).order_by(Document.created_at.desc()))
    return result.scalars().all()


@router.post("/upload", response_model=DocumentResponse, status_code=201)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    namespace: str = Form(default="default"),
    workspace_id: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    display_name, suffix = safe_filename(file.filename)
    namespace = validate_namespace(namespace)
    await require_workspace_role(db, workspace_id, current_user.id, "editor")
    file_path, file_size = await write_limited_upload(file, suffix, request.app.state.max_upload_bytes)
    previous = (await db.execute(select(Document).where(Document.workspace_id == workspace_id, Document.filename == display_name).order_by(Document.version.desc()))).scalars().first()
    document = Document(
        user_id=current_user.id,
        workspace_id=workspace_id,
        filename=display_name,
        file_size=file_size,
        file_type=suffix.lstrip("."),
        namespace=namespace,
        status="queued", stored_path=file_path,
        version=(previous.version + 1) if previous else 1,
        parent_document_id=previous.id if previous else None,
    )
    try:
        db.add(document); current_user.total_documents += 1
        await db.commit(); await db.refresh(document)
        await enqueue_ingestion(document.id)
        return document
    except Exception as error:
        await db.rollback(); logger.exception("Document queueing failed")
        raise HTTPException(500, "Could not queue document ingestion") from error
    finally:
        await file.close()
        # Worker owns cleanup after it has read the upload.

@router.get("/{document_id}/status")
async def document_status(document_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    document = (await db.execute(select(Document).where(Document.id == document_id))).scalar_one_or_none()
    if not document: raise HTTPException(404, "Document not found")
    await require_workspace_role(db, document.workspace_id, current_user.id)
    return {"id": document.id, "status": document.status, "progress": document.ingestion_progress, "error": document.ingestion_error, "version": document.version}


@router.get("/{document_id}/file")
async def serve_document_file(document_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Serve an original upload only after the same workspace check as chat."""
    document = (await db.execute(select(Document).where(Document.id == document_id))).scalar_one_or_none()
    if not document:
        raise HTTPException(404, "Document not found")
    await require_workspace_role(db, document.workspace_id, current_user.id)
    if not document.stored_path or not os.path.isfile(document.stored_path):
        raise HTTPException(404, "The original uploaded file is not available")
    media_type = mimetypes.guess_type(document.filename)[0] or "application/octet-stream"
    return FileResponse(document.stored_path, media_type=media_type, headers={"Content-Disposition": f'inline; filename="{document.filename}"'})


@router.get("/{document_id}/redactions")
async def list_document_redactions(document_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Owners can recover originals; regular chat/vector retrieval never sees them."""
    document = (await db.execute(select(Document).where(Document.id == document_id, Document.user_id == current_user.id))).scalar_one_or_none()
    if not document:
        raise HTTPException(404, "Document not found")
    await require_workspace_role(db, document.workspace_id, current_user.id)
    rows = (await db.execute(select(DocumentRedaction).where(
        DocumentRedaction.document_id == document_id, DocumentRedaction.user_id == current_user.id
    ).order_by(DocumentRedaction.created_at))).scalars().all()
    return [{"entity_type": row.entity_type, "replacement": row.replacement, "original_value": row.original_value, "source_page": row.source_page} for row in rows]


@router.delete("/{document_id}", status_code=204)
async def delete_document(document_id: str, request: Request, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    document = (await db.execute(select(Document).where(Document.id == document_id))).scalar_one_or_none()
    if not document:
        raise HTTPException(404, "Document not found")
    await require_workspace_role(db, document.workspace_id, current_user.id, "editor")
    try:
        if document.vector_ids:
            await request.app.state.vector_store.delete_documents(document.vector_ids)
        stored_path = document.stored_path
        await db.delete(document)
        current_user.total_documents = max(0, current_user.total_documents - 1)
        await db.commit()
        if stored_path and os.path.isfile(stored_path):
            os.remove(stored_path)
    except Exception as error:
        await db.rollback()
        logger.exception("Document deletion failed")
        raise HTTPException(500, "Document deletion failed") from error
