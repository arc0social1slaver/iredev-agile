"""Shared knowledge module for iReDev agents."""

from __future__ import annotations

import logging
import threading
import uuid
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import frontmatter
from langchain_community.document_loaders import PyPDFLoader
from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter

from ..config.config_manager import get_config
from ..agent.llm.factory import LLMFactory
from ..orchestrator import ProcessPhase

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

_MARKDOWN_HEADERS = [
    ("#",   "h1"),
    ("##",  "h2"),
    ("###", "h3"),
]

_SUPPORTED_EXTENSIONS = {".md", ".txt", ".pdf"}

# Over-fetch multiplier for similarity_search to survive deduplication:
# a single file may produce many chunks, so we fetch more than k
# and deduplicate by parent_id before capping at the requested k.
_CHUNK_OVERFETCH = 3


# ─────────────────────────────────────────────────────────────────────────────
# KnowledgeType
# ─────────────────────────────────────────────────────────────────────────────

class KnowledgeType(Enum):
    DOMAIN_KNOWLEDGE = "domain_knowledge"
    METHODOLOGY      = "methodology"
    STANDARDS        = "standards"
    TEMPLATES        = "templates"
    STRATEGIES       = "strategies"


_ALL_KNOWLEDGE_TYPES: Set[KnowledgeType] = set(KnowledgeType)

# Phase → allowed knowledge types.
# VALIDATION excludes STRATEGIES — all other phases allow everything.
_PHASE_ALLOWED_TYPES: Dict[ProcessPhase, Set[KnowledgeType]] = {
    ProcessPhase.ELICITATION:   _ALL_KNOWLEDGE_TYPES,
    ProcessPhase.ANALYSIS:      _ALL_KNOWLEDGE_TYPES,
    ProcessPhase.SPECIFICATION: _ALL_KNOWLEDGE_TYPES,
    ProcessPhase.VALIDATION: {
        KnowledgeType.DOMAIN_KNOWLEDGE,
        KnowledgeType.METHODOLOGY,
        KnowledgeType.STANDARDS,
        KnowledgeType.TEMPLATES,
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# File-system event handler (module-level for testability)
# ─────────────────────────────────────────────────────────────────────────────

def _make_watchdog_handler(module: "KnowledgeModule"):
    """Return a FileSystemEventHandler wired to *module*."""
    from watchdog.events import FileSystemEventHandler

    class _Handler(FileSystemEventHandler):
        def on_created(self, event) -> None:
            path = Path(event.src_path)
            if not event.is_directory and path.suffix in _SUPPORTED_EXTENSIONS:
                module._reindex_file(path)

        def on_modified(self, event) -> None:
            path = Path(event.src_path)
            if not event.is_directory and path.suffix in _SUPPORTED_EXTENSIONS:
                module._reindex_file(path)

        def on_deleted(self, event) -> None:
            if not event.is_directory:
                module._remove_file(Path(event.src_path))

    return _Handler()


# ─────────────────────────────────────────────────────────────────────────────
# KnowledgeModule — singleton
# ─────────────────────────────────────────────────────────────────────────────

class KnowledgeModule:
    """Process-wide knowledge store backed by PostgreSQL + pgvector.

    Chunks are indexed with MarkdownHeaderTextSplitter for accurate semantic
    search. Retrieval deduplicates by source file and returns full documents,
    since each knowledge file is designed to be read as a whole.

    Always use ``KnowledgeModule.get_instance()`` — do not instantiate directly.
    """

    _instance: Optional["KnowledgeModule"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        cfg = get_config().get("iredev", {}).get("knowledge_base", {})

        self._type_paths = self._resolve_type_paths(cfg)
        self._path_to_type: Dict[Path, KnowledgeType] = {
            path.resolve(): kt for kt, path in self._type_paths.items()
        }
        self._splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=_MARKDOWN_HEADERS,
            strip_headers=False,  # keep headings in chunk text for richer embeddings
        )

        # parent_id → full source Document (returned by retrieve())
        self._parent_store: Dict[str, Document] = {}
        # resolved file path → list of chunk IDs stored in the vector store
        self._file_chunk_ids: Dict[str, List[str]] = {}
        self._store_lock = threading.Lock()

        self._store = self._init_vector_store(cfg)
        self._index_all()
        self._observer = self._start_watchdog()

        logger.info("[KnowledgeModule] Ready — watching %d folders.", len(self._type_paths))

    # ── Singleton ─────────────────────────────────────────────────────────

    @classmethod
    def get_instance(cls) -> "KnowledgeModule":
        """Return (or create) the shared KnowledgeModule. Thread-safe."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ── Public API ────────────────────────────────────────────────────────

    def retrieve(
        self,
        query: str,
        phase: ProcessPhase,
        k: int = 5,
    ) -> List[Document]:
        """Semantic search filtered by phase; returns full source documents.

        Internally searches over fine-grained header chunks for precision,
        then resolves each hit back to its parent document. Results are
        deduplicated and capped at *k* unique files.
        """
        allowed = [kt.value for kt in _PHASE_ALLOWED_TYPES.get(phase, _ALL_KNOWLEDGE_TYPES)]
        chunks = self._store.similarity_search(
            query,
            k=k * _CHUNK_OVERFETCH,
            filter={"knowledge_type": {"$in": allowed}},
        )

        seen: Set[str] = set()
        results: List[Document] = []
        for chunk in chunks:
            parent_id = chunk.metadata.get("parent_id", "")
            if not parent_id or parent_id in seen:
                continue
            seen.add(parent_id)
            parent = self._parent_store.get(parent_id)
            if parent:
                results.append(parent)
            if len(results) >= k:
                break

        return results

    # ── Initialisation helpers ────────────────────────────────────────────

    @staticmethod
    def _resolve_type_paths(cfg: Dict[str, Any]) -> Dict[KnowledgeType, Path]:
        project_root = Path(__file__).resolve().parents[2]

        def _resolve(p: str) -> Path:
            path = Path(p)
            return path if path.is_absolute() else project_root / path

        return {
            KnowledgeType.DOMAIN_KNOWLEDGE: _resolve(cfg["domain_knowledge_path"]),
            KnowledgeType.METHODOLOGY:      _resolve(cfg["methodology_path"]),
            KnowledgeType.STANDARDS:        _resolve(cfg["standards_path"]),
            KnowledgeType.TEMPLATES:        _resolve(cfg["templates_path"]),
            KnowledgeType.STRATEGIES:       _resolve(cfg["strategies_path"]),
        }

    def _init_vector_store(self, cfg: Dict[str, Any]):
        from langchain_postgres import PGVector

        pg_conn_str = cfg.get("pg_connection")
        logger.info("[KnowledgeModule] Connecting to: %s", pg_conn_str.split("@")[-1])

        embeddings = LLMFactory.create_embeddings(cfg.get("embedding", {}))
        collection = cfg.get("collection_name", "iredev_knowledge")

        try:
            store = PGVector(
                connection=pg_conn_str,
                embeddings=embeddings,
                collection_name=collection,
                use_jsonb=True,
            )
            logger.info("[KnowledgeModule] Vector store connected.")
            return store
        except Exception as exc:
            raise RuntimeError(
                f"[KnowledgeModule] Failed to connect to PGVector at "
                f"'{pg_conn_str.split('@')[-1]}': {exc}"
            ) from exc

    # ── Indexing ──────────────────────────────────────────────────────────

    def _index_all(self) -> None:
        total = 0
        for kt, folder in self._type_paths.items():
            if not folder.exists():
                logger.warning("[KnowledgeModule] Folder missing, skipping: %s", folder)
                continue
            docs = self._load_folder(folder, kt)
            if not docs:
                logger.warning("[KnowledgeModule] No documents found in: %s", folder)
                continue
            for doc in docs:
                self._add_document(doc)
            total += len(docs)
            logger.debug("[KnowledgeModule] Indexed %d doc(s) from %s.", len(docs), folder)

        logger.info("[KnowledgeModule] Total documents indexed: %d.", total)

    def _add_document(self, doc: Document) -> None:
        """Split *doc* into header chunks, index them, and register the parent."""
        parent_id = str(uuid.uuid4())
        doc.metadata["parent_id"] = parent_id

        raw_chunks = self._splitter.split_text(doc.page_content)
        # If no headers found, fall back to indexing the whole document as one chunk.
        chunk_docs = [
            Document(page_content=chunk.page_content, metadata={**doc.metadata, **chunk.metadata})
            for chunk in raw_chunks
        ] if raw_chunks else [doc]

        ids = self._store.add_documents(chunk_docs)
        source = doc.metadata.get("source", "")

        with self._store_lock:
            self._parent_store[parent_id] = doc
            self._file_chunk_ids.setdefault(source, []).extend(ids)

    def _load_folder(self, folder: Path, kt: KnowledgeType) -> List[Document]:
        docs: List[Document] = []
        for path in folder.rglob("*"):
            if path.suffix in {".md", ".txt"}:
                docs.extend(self._load_markdown(path, kt))
            elif path.suffix == ".pdf":
                docs.extend(self._load_pdf(path, kt))
        return docs

    def _load_markdown(self, path: Path, kt: KnowledgeType) -> List[Document]:
        """Load a Markdown/text file; parse YAML front-matter with python-frontmatter."""
        try:
            post = frontmatter.load(str(path))
        except Exception as exc:
            logger.warning("[KnowledgeModule] Could not parse %s: %s", path, exc)
            return []

        return [Document(
            page_content=post.content,
            metadata=self._build_metadata(path, kt, post.metadata),
        )]

    def _load_pdf(self, path: Path, kt: KnowledgeType) -> List[Document]:
        """Load a PDF; all pages share the same base metadata."""
        docs = PyPDFLoader(str(path)).load()
        base_meta = self._build_metadata(path, kt)
        for doc in docs:
            doc.metadata.update(base_meta)
        return docs

    def _build_metadata(
        self,
        path: Path,
        kt: KnowledgeType,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Construct the standard metadata dict for a knowledge document."""
        extra = extra or {}
        all_phases = [p.value for p in ProcessPhase]
        return {
            "source":         str(path.resolve()),
            "knowledge_type": kt.value,
            "title":          extra.get("title", path.stem),
            "phases":         extra.get("phases", all_phases),
        }

    # ── Hot-reload ────────────────────────────────────────────────────────

    def _reindex_file(self, path: Path) -> None:
        """Re-index a file's current content, replacing any stale entries.

        Load first so a parse failure leaves the existing index intact.
        """
        kt = self._infer_type(path)
        if kt is None:
            return

        loader = self._load_markdown if path.suffix in {".md", ".txt"} else self._load_pdf
        new_docs = loader(path, kt)
        if not new_docs:
            logger.warning("[KnowledgeModule] Could not load %s — keeping stale index.", path)
            return

        self._remove_file(path)
        for doc in new_docs:
            self._add_document(doc)

    def _remove_file(self, path: Path) -> None:
        """Remove all chunks and parent entries for *path* from the stores."""
        source = str(path.resolve())
        with self._store_lock:
            chunk_ids = self._file_chunk_ids.pop(source, [])
            stale_parent_ids = [
                pid for pid, doc in self._parent_store.items()
                if doc.metadata.get("source") == source
            ]
            for pid in stale_parent_ids:
                del self._parent_store[pid]

        if chunk_ids:
            self._store.delete(ids=chunk_ids)

    def _infer_type(self, path: Path) -> Optional[KnowledgeType]:
        """Walk *path*'s ancestors to find which knowledge folder it belongs to."""
        for ancestor in [path.resolve(), *path.resolve().parents]:
            kt = self._path_to_type.get(ancestor)
            if kt is not None:
                return kt
        return None

    # ── Watchdog ──────────────────────────────────────────────────────────

    def _start_watchdog(self):
        from watchdog.observers import Observer

        observer = Observer()
        handler = _make_watchdog_handler(self)
        for folder in self._type_paths.values():
            folder.mkdir(parents=True, exist_ok=True)
            observer.schedule(handler, str(folder), recursive=True)
        observer.start()
        logger.info("[KnowledgeModule] Watchdog started on %d folders.", len(self._type_paths))
        return observer