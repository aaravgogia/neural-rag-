import logging
import hashlib
import re
from typing import List, Optional
from pathlib import Path

try:  # Keep this module importable with the newer developer LangChain split.
    from langchain.text_splitter import RecursiveCharacterTextSplitter
except ModuleNotFoundError:  # pragma: no cover - production pins the first path
    from langchain_text_splitters import RecursiveCharacterTextSplitter
try:
    from langchain.schema import Document
except ModuleNotFoundError:  # pragma: no cover - newer LangChain
    from langchain_core.documents import Document

from app.core.pii_redaction import PIIRedactor, Redaction

logger = logging.getLogger(__name__)

class DocumentProcessor:
    """Processes uploaded documents into chunks for embedding."""

    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            length_function=len,
            separators=["\n\n", "\n", " ", ""]
        )
        self.loaders = {".pdf", ".docx", ".txt", ".html"}
        self.redactor = PIIRedactor()
        # Kept on the processor only until the upload route persists mappings
        # to document_redactions; never copied to Document metadata/chunks.
        self.last_redactions: list[tuple[Redaction, int | None]] = []

    def _redact_documents(self, documents: List[Document]) -> List[Document]:
        self.last_redactions = []
        for doc in documents:
            redacted, matches = self.redactor.redact(doc.page_content)
            doc.page_content = redacted
            if matches:
                page = doc.metadata.get("page")
                page_number = int(page) if isinstance(page, int) or (isinstance(page, str) and page.isdigit()) else None
                self.last_redactions.extend((match, page_number) for match in matches)
                doc.metadata["pii_redacted"] = True
                doc.metadata["pii_redaction_count"] = len(matches)
        return documents

    async def process_document(self, file_path: str, metadata: Optional[dict] = None) -> List[Document]:
        path = Path(file_path)
        extension = path.suffix.lower()
        if extension not in self.loaders:
            raise ValueError(f"Unsupported file format: {extension}")

        # Loader imports stay on the full ingestion path. main_demo does not
        # expose uploads and therefore never needs langchain-community/Presidio.
        from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader, TextLoader, UnstructuredHTMLLoader
        loader_class = {".pdf": PyPDFLoader, ".docx": Docx2txtLoader, ".txt": TextLoader, ".html": UnstructuredHTMLLoader}[extension]
        loader = loader_class(file_path)
        documents = loader.load()

        if metadata:
            for doc in documents:
                doc.metadata.update(metadata)

        chunks = self._with_hashes(self.text_splitter.split_documents(self._redact_documents(documents)))
        logger.info(f"Processed {path.name}: {len(chunks)} chunks created")
        return chunks

    async def process_text(self, text: str, metadata: Optional[dict] = None) -> List[Document]:
        doc = Document(page_content=text, metadata=metadata or {})
        return self._with_hashes(self.text_splitter.split_documents(self._redact_documents([doc])))

    @staticmethod
    def _chunk_hash(text: str) -> str:
        return hashlib.sha256(re.sub(r"\s+", " ", text).strip().lower().encode("utf-8")).hexdigest()

    def _with_hashes(self, chunks: List[Document]) -> List[Document]:
        for chunk in chunks:
            chunk.metadata["chunk_hash"] = self._chunk_hash(chunk.page_content)
        return chunks
