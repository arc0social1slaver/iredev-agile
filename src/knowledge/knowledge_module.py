"""Shared knowledge module for iReDev agents.

Indexes the local knowledge base into a PostgreSQL vector store (pgvector)
and exposes phase-filtered semantic retrieval for ThinkModule to inject
into agent prompts.

Knowledge files live under the paths declared in config.knowledge_base:
    knowledge/domains/          -> KnowledgeType.DOMAIN_KNOWLEDGE
    knowledge/methodologies/    -> KnowledgeType.METHODOLOGY
    knowledge/standards/        -> KnowledgeType.STANDARDS
    knowledge/templates/        -> KnowledgeType.TEMPLATES
    knowledge/strategies/       -> KnowledgeType.STRATEGIES

Each .md / .txt / .pdf file may carry a YAML front-matter block to declare
which phases the document applies to:

    ---
    phases: [elicitation, analysis]
    title: "Interview Techniques"
    ---
    # Interview Techniques
    ...

Files without front-matter are indexed under ALL phases.

Import-time side effects:
    This module imports only stdlib, yaml, and local enum types at module level.
    All heavy drivers (langchain_postgres, watchdog, langchain_text_splitters) are
    imported lazily inside the methods that first need them so that a bare
    `from src.modules.knowledge import KnowledgeModule` has zero runtime cost.
"""

import logging
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import yaml

from src.config.config_manager import KnowledgeType, get_config
from src.orchestrator import ProcessPhase

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Phase -> knowledge-type coverage (iReDev paper, Table 1)
# Lightweight: just enum sets, no driver initialization.
# ---------------------------------------------------------------------------

_PHASE_TYPES: Dict[ProcessPhase, Set[KnowledgeType]] = {
    ProcessPhase.ELICITATION: {
        KnowledgeType.DOMAIN_KNOWLEDGE,
        KnowledgeType.METHODOLOGY,
        KnowledgeType.STANDARDS,
        KnowledgeType.TEMPLATES,
        KnowledgeType.STRATEGIES,
    },
    ProcessPhase.ANALYSIS: {
        KnowledgeType.DOMAIN_KNOWLEDGE,
        KnowledgeType.METHODOLOGY,
        KnowledgeType.STANDARDS,
        KnowledgeType.TEMPLATES,
        KnowledgeType.STRATEGIES,
    },
    ProcessPhase.SPECIFICATION: {
        KnowledgeType.DOMAIN_KNOWLEDGE,
        KnowledgeType.METHODOLOGY,
        KnowledgeType.STANDARDS,
        KnowledgeType.TEMPLATES,
        KnowledgeType.STRATEGIES,
    },
    ProcessPhase.VALIDATION: {
        KnowledgeType.DOMAIN_KNOWLEDGE,
        KnowledgeType.METHODOLOGY,
        KnowledgeType.STANDARDS,
        KnowledgeType.TEMPLATES,
    },
}

_SUPPORTED_EXTENSIONS = {".md", ".txt", ".pdf", ".yaml", ".yml"}


# ---------------------------------------------------------------------------
# Embedding factory (lazy imports inside)
# ---------------------------------------------------------------------------

def _create_embeddings(embed_cfg: Dict[str, Any]):
    """Build a LangChain Embeddings instance from the embedding config block.

    Supported providers:
      "openai"      -- OpenAI cloud OR any OpenAI-compatible endpoint (e.g. Ollama).
                       Set base_url to point to a local server.
      "huggingface" -- Local sentence-transformers model, no API key needed.

    Config examples:

        # Ollama local embedding (nomic-embed-text)
        embedding:
          type: "openai"
          model: "nomic-embed-text"
          api_key: "EMPTY"
          base_url: "http://localhost:11434/v1"
          dims: 768

        # OpenAI cloud
        embedding:
          type: "openai"
          model: "text-embedding-3-small"
          api_key: "sk-..."
          dims: 1536

        # HuggingFace local
        embedding:
          type: "huggingface"
          model: "sentence-transformers/all-MiniLM-L6-v2"
          dims: 384

    Args:
        embed_cfg: Embedding sub-dict from config.knowledge_base.

    Returns:
        LangChain Embeddings instance.

    Raises:
        ValueError: If provider is unsupported or model is missing.
    """
    provider = embed_cfg.get("type", "openai").lower()
    model = embed_cfg.get("model")
    if not model:
        raise ValueError("knowledge_base.embedding.model must be specified.")

    if provider in ("google", "gemini"):
        from langchain_google_genai import GoogleGenerativeAIEmbeddings
        return GoogleGenerativeAIEmbeddings(
            model=model,
            api_key=embed_cfg.get("api_key")
        )

    if provider == "openai":
        from langchain_openai import OpenAIEmbeddings
        kwargs: Dict[str, Any] = {
            "model": model,
            "api_key": embed_cfg.get("api_key"),
            # OpenAIEmbeddings normally tokenizes text and sends integer token IDs.
            # Ollama (and most local servers) only accept plain text strings, so we
            # disable the tokenization step to send raw text instead.
            "check_embedding_ctx_length": False,
        }
        # base_url lets the same provider type point to Ollama or any local server
        if embed_cfg.get("base_url"):
            kwargs["base_url"] = embed_cfg["base_url"]
        return OpenAIEmbeddings(**kwargs)

    if provider == "huggingface":
        from langchain_huggingface import HuggingFaceEmbeddings
        return HuggingFaceEmbeddings(model_name=model)

    raise ValueError(f"Unsupported embedding provider: '{provider}'")


# ---------------------------------------------------------------------------
# KnowledgeModule -- singleton
# ---------------------------------------------------------------------------

class KnowledgeModule:
    """Shared, process-wide knowledge store backed by PostgreSQL + pgvector.

    Singleton: use KnowledgeModule.get_instance() -- do not instantiate directly.

    On first call to get_instance():
      1. Loads config from get_config().knowledge_base.
      2. Imports and initializes PGVector (lazy -- happens only here).
      3. Imports and starts a watchdog Observer (lazy -- happens only here).
      4. Indexes all existing knowledge files.

    All heavy driver imports (langchain_postgres, watchdog, langchain_text_splitters)
    are deferred to __init__ so that importing this module has zero cost.
    """

    _instance: Optional["KnowledgeModule"] = None
    _lock = threading.Lock()

    def __init__(self, pg_conn_str: Optional[str] = None) -> None:
        # self._config: Dict[str, Any] = get_config().knowledge_base
        # self._pg_conn_str = pg_conn_str
        #
        # self._type_paths: Dict[KnowledgeType, Path] = {
        #     KnowledgeType.DOMAIN_KNOWLEDGE: Path(
        #         self._config.get("domain_knowledge_path", "knowledge/domains")
        #     ),
        #     KnowledgeType.METHODOLOGY: Path(
        #         self._config.get("methodology_path", "knowledge/methodologies")
        #     ),
        #     KnowledgeType.STANDARDS: Path(
        #         self._config.get("standards_path", "knowledge/standards")
        #     ),
        #     KnowledgeType.TEMPLATES: Path(
        #         self._config.get("templates_path", "knowledge/templates")
        #     ),
        #     KnowledgeType.STRATEGIES: Path(
        #         self._config.get("strategies_path", "knowledge/strategies")
        #     ),
        # }

        # ------------------------------------------------------------------ #
        # Load knowledge_base config from the central config system.           #
        # The orchestrator (or any caller) must have called                    #
        # get_config_manager(path) before get_instance() so that the correct  #
        # config file is already loaded.                                        #
        # ------------------------------------------------------------------ #
        self._config: Dict[str, Any] = get_config().knowledge_base

        # pg_conn_str can be supplied explicitly (e.g. from the orchestrator)
        # or read from the config; explicit argument always wins.

        logger.info("[KnowledgeModule] Initializing with config: %s", self._config.get("pg_connection"))
        self._pg_conn_str = pg_conn_str or self._config.get(
            "pg_connection",
            "postgresql+psycopg://postgres:postgres@localhost:5432/iredev",
        )

        # Resolve project root: this file lives at src/knowledge/knowledge_module.py
        # so the project root is two levels up — same convention as config_manager.py.
        # This ensures knowledge/ folder is found regardless of the working directory
        # the script is launched from.
        _project_root = Path(__file__).resolve().parent.parent.parent

        def _resolve_path(cfg_key: str, default: str) -> Path:
            """Return an absolute Path: honour absolute paths from config as-is,
            resolve relative ones against the project root (not CWD)."""
            raw = self._config.get(cfg_key, default)
            p = Path(raw)
            return p if p.is_absolute() else _project_root / p

        self._type_paths: Dict[KnowledgeType, Path] = {
            KnowledgeType.DOMAIN_KNOWLEDGE: _resolve_path(
                "domain_knowledge_path", "knowledge/domains"
            ),
            KnowledgeType.METHODOLOGY: _resolve_path(
                "methodology_path", "knowledge/methodologies"
            ),
            KnowledgeType.STANDARDS: _resolve_path(
                "standards_path", "knowledge/standards"
            ),
            KnowledgeType.TEMPLATES: _resolve_path(
                "templates_path", "knowledge/templates"
            ),
            KnowledgeType.STRATEGIES: _resolve_path(
                "strategies_path", "knowledge/strategies"
            ),
        }

        # Reverse lookup: resolved folder path -> KnowledgeType
        self._path_to_type: Dict[Path, KnowledgeType] = {
            v.resolve(): k for k, v in self._type_paths.items()
        }

        # source_file (str) -> list of vector-store IDs for clean deletion
        self._file_ids: Dict[str, List[str]] = {}
        self._ids_lock = threading.Lock()

        # Lazy import: RecursiveCharacterTextSplitter loads tokenizer deps
        from langchain_text_splitters import RecursiveCharacterTextSplitter
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=self._config.get("chunk_size", 800),
            chunk_overlap=self._config.get("chunk_overlap", 100),
        )

        self._store = self._setup_vector_store()
        self._index_all()
        self._observer = self._start_watchdog()

        logger.info("[KnowledgeModule] Initialized and watching knowledge folders.")

    # ------------------------------------------------------------------
    # Singleton factory
    # ------------------------------------------------------------------

    @classmethod
    def get_instance(cls, pg_conn_str: Optional[str] = None) -> "KnowledgeModule":
        """Return the shared KnowledgeModule, creating it on first call.

        Thread-safe. The pg_conn_str is optional: if omitted, the connection
        string is read from ``get_config().knowledge_base["pg_connection"]``.
        Subsequent calls with a different pg_conn_str are ignored; the first
        connection string wins for the lifetime of the process.

        Before calling this method, the orchestrator (or main entry point) must
        have initialized the config system via::

            from src.config.config_manager import get_config_manager
            get_config_manager("config/iredev_config.yaml")

        Args:
            pg_conn_str: Optional PostgreSQL connection string override.

        Returns:
            The singleton KnowledgeModule instance.
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(pg_conn_str)
        return cls._instance

    # ------------------------------------------------------------------
    # Public retrieval API
    # ------------------------------------------------------------------

    def retrieve(
        self,
        query: str,
        phase: ProcessPhase,
        k: int = 5,
    ) -> List[Any]:
        """Retrieve the top-k knowledge snippets most relevant to query.

        Two-stage filtering:
          1. knowledge_type filter pushed to Postgres via PGVector metadata filter
             (SQL WHERE on cmetadata JSONB -- fast, runs before vector ranking).
          2. phases list checked in Python -- JSONB array containment is not
             uniformly supported across PGVector versions, so this stays in Python.

        Args:
            query: Natural language question or rewritten retrieval query.
            phase: Current process phase -- restricts which knowledge applies.
            k: Desired number of results to return.

        Returns:
            List of Document objects (page_content + metadata).
        """
        relevant_types = [kt.value for kt in _PHASE_TYPES.get(phase, set())]
        if not relevant_types:
            return []

        # Push knowledge_type to Postgres -- reduces vector ranking scope.
        # PGVector filter syntax: {"field": {"$in": [...]}} for list membership.
        pg_filter = {"knowledge_type": {"$in": relevant_types}}

        candidates = self._store.similarity_search(
            query,
            k=k * 4,
            filter=pg_filter,
        )

        # Python post-filter: only keep chunks tagged for this phase
        filtered = [
            doc for doc in candidates
            if phase.value in doc.metadata.get("phases", [])
        ]
        return filtered[:k]

    def shutdown(self) -> None:
        """Stop the watchdog observer on process exit."""
        if self._observer and self._observer.is_alive():
            self._observer.stop()
            self._observer.join()
            logger.info("[KnowledgeModule] Watchdog stopped.")

    # ------------------------------------------------------------------
    # Internal -- vector store setup (lazy import: langchain_postgres)
    # ------------------------------------------------------------------

    def _setup_vector_store(self):
        """Build the PGVector store from embedding config.

        Lazy-imports langchain_postgres here so the driver is only loaded
        when the singleton is actually created, not at module import time.

        Returns:
            Configured PGVector instance.
        """
        from langchain_postgres import PGVector

        embed_cfg = self._config.get("embedding", {})
        embeddings = _create_embeddings(embed_cfg)
        store = PGVector(
            embeddings=embeddings,
            collection_name=self._config.get("collection_name", "iredev_knowledge"),
            connection=self._pg_conn_str,
            use_jsonb=True,
        )
        logger.info("[KnowledgeModule] Vector store connected.")
        return store

    # ------------------------------------------------------------------
    # Internal -- indexing
    # ------------------------------------------------------------------

    def _index_all(self) -> None:
        """Walk all knowledge type folders and index every supported file."""
        total_files = 0
        empty_folders = []

        for knowledge_type, folder in self._type_paths.items():
            if not folder.exists():
                logger.warning("[KnowledgeModule] Folder not found, skipping: %s", folder)
                continue

            files = [
                p for p in folder.rglob("*")
                if p.is_file() and p.suffix in _SUPPORTED_EXTENSIONS
            ]

            if not files:
                empty_folders.append(folder)
                logger.warning(
                    "[KnowledgeModule] No knowledge files in '%s' "
                    "(supported: %s). Add .md/.txt/.pdf files here.",
                    folder, "/".join(_SUPPORTED_EXTENSIONS),
                )
                continue

            for path in files:
                self._index_file(path, knowledge_type=knowledge_type)
                total_files += 1

        if total_files == 0:
            logger.warning(
                "[KnowledgeModule] No knowledge files indexed. "
                "The knowledge base is EMPTY — retrieve() will always return []. "
                "Populate the following folders with .md/.txt/.pdf files:\n%s",
                "\n".join(f"  {f}" for f in self._type_paths.values()),
            )
        else:
            logger.info(
                "[KnowledgeModule] Indexed %d file(s) across %d folder(s). Empty: %d.",
                total_files,
                len(self._type_paths) - len(empty_folders),
                len(empty_folders),
            )

    def _index_file(
        self,
        path: Path,
        knowledge_type: Optional[KnowledgeType] = None,
    ) -> None:
        """Load, parse, chunk, and upsert one knowledge file into the vector store.

        Front-matter YAML (if present) is stripped from content and merged
        into each chunk's metadata. Files without front-matter are tagged to
        all phases.

        Args:
            path: Path to the file to index.
            knowledge_type: Override type inference -- inferred from path if None.
        """
        if knowledge_type is None:
            knowledge_type = self._infer_type(path)
        if knowledge_type is None:
            logger.debug("[KnowledgeModule] Cannot infer type for %s, skipping.", path)
            return

        content, front_matter = self._load_file(path)
        if not content.strip():
            return

        all_phases = [p.value for p in ProcessPhase]
        phases: List[str] = front_matter.get("phases", all_phases)
        title: str = front_matter.get("title", path.stem)

        base_metadata = {
            "source_file": str(path.resolve()),
            "knowledge_type": knowledge_type.value,
            "phases": phases,
            "title": title,
        }

        chunks = self._splitter.create_documents(texts=[content], metadatas=[base_metadata])
        ids = self._store.add_documents(chunks)

        with self._ids_lock:
            self._file_ids[str(path.resolve())] = ids

        logger.debug(
            "[KnowledgeModule] Indexed %d chunks from '%s' (type=%s, phases=%s).",
            len(chunks), path.name, knowledge_type.value, phases,
        )

    def _reindex_file(self, path: Path) -> None:
        """Remove stale chunks for a file then re-index it.

        Args:
            path: Path to the modified file.
        """
        self._remove_file(path)
        self._index_file(path)

    def _remove_file(self, path: Path) -> None:
        """Delete all vector-store entries originating from a file.

        Args:
            path: Path to the deleted or moved file.
        """
        key = str(path.resolve())
        with self._ids_lock:
            ids = self._file_ids.pop(key, [])
        if ids:
            self._store.delete(ids=ids)
            logger.debug("[KnowledgeModule] Removed %d chunks for '%s'.", len(ids), path.name)

    # ------------------------------------------------------------------
    # Internal -- file loading and front-matter parsing
    # ------------------------------------------------------------------

    def _load_file(self, path: Path):
        """Load file content and strip YAML front-matter if present.

        Supports .md/.txt (optional YAML front-matter), .pdf, and .yaml/.yml.

        For .yaml/.yml files the entire document is treated as structured
        knowledge: if it is a mapping with a "content" key, that key is used
        as the text body and the remaining keys become front-matter metadata
        (including an optional "phases" list).  Otherwise the whole document
        is serialised back to a human-readable YAML string so the LLM can read
        it naturally.

        Args:
            path: File to read (.md, .txt, .pdf, .yaml, or .yml).

        Returns:
            Tuple of (content: str, front_matter: dict).
        """
        if path.suffix == ".pdf":
            return self._load_pdf(path), {}

        if path.suffix in (".yaml", ".yml"):
            return self._load_yaml(path)

        raw = path.read_text(encoding="utf-8", errors="ignore")
        return self._split_front_matter(raw)

    @staticmethod
    def _load_yaml(path: Path):
        """Load a .yaml/.yml knowledge file.

        Convention:
          - If the document is a dict with a top-level content key, that
            key is used as the text body; all other keys become front-matter
            (useful for phases, title, etc.).
          - Otherwise the whole document is dumped back to a YAML string so
            the LLM can read it as structured text.

        Args:
            path: YAML file to load.

        Returns:
            Tuple of (text_body: str, front_matter: dict).
        """
        import yaml as _yaml  # already imported at module level, alias for clarity
        raw = path.read_text(encoding="utf-8", errors="ignore")
        try:
            doc = _yaml.safe_load(raw)
        except _yaml.YAMLError:
            # Fall back to raw text if parsing fails
            return raw, {}

        if isinstance(doc, dict):
            if "content" in doc:
                # Structured format: separate content from metadata
                front_matter = {k: v for k, v in doc.items() if k != "content"}
                return str(doc["content"]), front_matter
            else:
                # Flat dict: dump the whole thing as readable text
                front_matter = {k: doc[k] for k in ("phases", "title") if k in doc}
                body_dict = {k: v for k, v in doc.items() if k not in ("phases", "title")}
                text_body = _yaml.dump(body_dict, allow_unicode=True, default_flow_style=False)
                return text_body, front_matter

        # List or scalar: just stringify
        return str(doc), {}

    @staticmethod
    def _load_pdf(path: Path) -> str:
        """Extract plain text from a PDF using LangChain's PyPDFLoader.

        Lazy-imports langchain_community so PDF support is optional at runtime.

        Args:
            path: PDF file to load.

        Returns:
            Concatenated text from all pages.
        """
        from langchain_community.document_loaders import PyPDFLoader
        loader = PyPDFLoader(str(path))
        pages = loader.load()
        return "\n\n".join(p.page_content for p in pages)

    @staticmethod
    def _split_front_matter(raw: str):
        """Parse YAML front-matter delimited by --- at the top of a text file.

        Args:
            raw: Full file text.

        Returns:
            Tuple of (body_text: str, metadata_dict: dict).
        """
        if not raw.startswith("---"):
            return raw, {}
        parts = raw.split("---", 2)
        if len(parts) < 3:
            return raw, {}
        try:
            meta = yaml.safe_load(parts[1]) or {}
        except yaml.YAMLError:
            meta = {}
        return parts[2].strip(), meta

    # ------------------------------------------------------------------
    # Internal -- type inference from path
    # ------------------------------------------------------------------

    def _infer_type(self, path: Path) -> Optional[KnowledgeType]:
        """Walk up the directory tree to find which type root this file belongs to.

        Args:
            path: File path to classify.

        Returns:
            KnowledgeType if found, None otherwise.
        """
        resolved = path.resolve()
        for parent in [resolved] + list(resolved.parents):
            kt = self._path_to_type.get(parent)
            if kt is not None:
                return kt
        return None

    # ------------------------------------------------------------------
    # Internal -- watchdog setup (lazy import: watchdog)
    # ------------------------------------------------------------------

    def _start_watchdog(self):
        """Start a watchdog observer on all configured knowledge folders.

        Lazy-imports watchdog here so the OS-level filesystem monitor is only
        registered when the singleton is actually created, not at module import time.

        Returns:
            Running Observer thread.
        """
        from watchdog.events import (
            FileCreatedEvent,
            FileDeletedEvent,
            FileModifiedEvent,
            FileSystemEventHandler,
        )
        from watchdog.observers import Observer

        module_ref = self

        class _Handler(FileSystemEventHandler):
            """Forwards filesystem events to the owning KnowledgeModule."""

            def on_created(self, event: FileCreatedEvent) -> None:
                if not event.is_directory and Path(event.src_path).suffix in _SUPPORTED_EXTENSIONS:
                    logger.info("[KnowledgeModule] New file: %s", event.src_path)
                    module_ref._index_file(Path(event.src_path))

            def on_modified(self, event: FileModifiedEvent) -> None:
                if not event.is_directory and Path(event.src_path).suffix in _SUPPORTED_EXTENSIONS:
                    logger.info("[KnowledgeModule] Modified: %s", event.src_path)
                    module_ref._reindex_file(Path(event.src_path))

            def on_deleted(self, event: FileDeletedEvent) -> None:
                if not event.is_directory:
                    logger.info("[KnowledgeModule] Deleted: %s", event.src_path)
                    module_ref._remove_file(Path(event.src_path))

        handler = _Handler()
        observer = Observer()
        for folder in self._type_paths.values():
            folder.mkdir(parents=True, exist_ok=True)
            observer.schedule(handler, str(folder), recursive=True)
        observer.start()
        logger.info("[KnowledgeModule] Watchdog started on %d folders.", len(self._type_paths))
        return observer