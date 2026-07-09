from __future__ import annotations
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal
import yaml
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG_FILE = BASE_DIR / "config" / "config.yaml"

def _load_yaml() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    with open( CONFIG_FILE, encoding="utf-8" ) as f:
        return yaml.safe_load(f) or {}

class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file= str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "RAG Enterprise Compet-e Legal"
    app_version: str = "0.1.0"
    app_description: str = "RAG Enterprise per documenti legali"
    app_debug: bool = False
    app_environment: Literal["development", "staging", "production"] = "development"

    llm_provider: str = "ollama"
    llm_model: str = "llama3.1"
    llm_base_url: str = "http://ollama:11434"
    llm_api_key: str = ""
    llm_temperature: float = 0.0
    llm_max_tokens: int = 2048
    llm_timeout: int = 120
    llm_streaming: bool = True
    llm_num_ctx: int = 2048

    embeddings_provider: str = "fastembed"
    embeddings_model: str = "BAAI/BGE-M3"
    embeddings_base_url: str = ""
    embeddings_batch_size: int = 64
    embeddings_cache_dir: str = "/app/.cache/embeddings"

    qdrant_url: str = "http://qdrant:6333"
    qdrant_api_key: str = ""
    qdrant_collection_name: str = "collection-rag-v2"
    qdrant_use_sparse: bool = True
    qdrant_force_recreate: bool = False
    qdrant_distance: str = "Cosine"
    qdrant_on_disk_payload: bool = True

    sqlserver_host: str = "sqlserver"
    sqlserver_port: int = 1433
    sqlserver_db: str = "RAGChat"
    sqlserver_password: str = ""
    sqlserver_driver: str = "ODBC Driver 18 for SQL Server"

    @property
    def sqlserver_url(self) -> str:
        return (
            f"mssql+pyodbc://SA:{self.sqlserver_password}@"
            f"{self.sqlserver_host}:{self.sqlserver_port}/"
            f"{self.sqlserver_db}"
            f"?driver={self.sqlserver_driver.replace(' ', '+')}"
            f"&TrustServerCertificate=yes"
            f"&Encrypt=yes"
        )

    redis_url: str = "redis://redis:6379/0"
    redis_cache_url: str = "redis://redis:6379/1"
    redis_password: str = ""

    retriever_search_type: str = "hybrid"
    retriever_strategy: str = "mmr"
    retriever_top_k: int = 20
    retriever_mmr_lambda: float = 0.5
    retriever_auto_filter: bool = False

    reranker_enabled: bool = True
    reranker_model: str = "BAAI/bge-reranker-base"
    reranker_top_k: int = 5
    reranker_initial_k: int = 20

    ingestion_prefer_docling: bool = True
    ingestion_extract_tables: bool = True
    ingestion_chunk_size: int = 1000
    ingestion_chunk_overlap: int = 200
    ingestion_chunk_strategy: str = "markdown"
    ingestion_max_file_mb: int = 100

    memory_short_term_turns: int = 10
    memory_long_term_enabled: bool = False
    memory_session_ttl_hours: int = 24

    cache_query_ttl_seconds: int = 3600
    cache_session_ttl_seconds: int = 86400

    jwt_secret_key: str = Field(default="change-me-in-production-min-32-chars")
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60
    api_key_length: int = 32
    password_min_length: int = 12

    rate_limit_requests_per_minute: int = 60
    rate_limit_tokens_per_day: int = 100_000

    langsmith_enabled: bool = False
    langsmith_api_key: str = ""
    langsmith_project: str = "rag-enterprise-legal"
    langsmith_endpoint: str = "https://eu.api.smith.langchain.com"
    opentelemetry_enabled: bool = False

    log_level: str = "INFO"
    log_console_output: bool = True
    log_colored: bool = True
    log_json_output: bool = False

    web_search_enabled: bool = False
    web_search_provider: str = "tavily"
    web_search_max_results: int = 5
    tavily_api_key: str = ""
    metadata_config_file: str = "/app/config/metadata.yaml"

    celery_broker_url: str = "redis://redis:6379/0"
    celery_result_backend: str = "redis://redis:6379/0"

    openai_api_key: str = ""
    google_api_key: str = ""
    ollama_api_key: str = ""

    @field_validator("jwt_secret_key")
    @classmethod
    def validate_jwt_secret(cls, v: str) -> str:
        if v == "change-me-in-production-min-32-chars":
            return v
        if len(v) < 32:
            raise ValueError("JWT_SECRET_KEY deve essere almeno 32 caratteri")
        return v

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        v = v.upper()
        if v not in allowed:
            raise ValueError(f"log_level deve essere uno di {allowed}")
        return v

def _apply_yaml_overrides() -> None:
    cfg = _load_yaml()
    if not cfg:
        return
    mappings: list[tuple[str, str]] = [

        ("llm.provider",            "LLM_PROVIDER"),
        ("llm.model",               "LLM_MODEL"),
        ("llm.base_url",            "LLM_BASE_URL"),
        ("llm.temperature",         "LLM_TEMPERATURE"),
        ("llm.max_tokens",          "LLM_MAX_TOKENS"),
        ("llm.timeout",             "LLM_TIMEOUT"),
        ("llm.num_ctx",             "LLM_NUM_CTX"),
        ("embeddings.provider",     "EMBEDDINGS_PROVIDER"),
        ("embeddings.model",        "EMBEDDINGS_MODEL"),
        ("embeddings.batch_size",   "EMBEDDINGS_BATCH_SIZE"),
        ("embeddings.cache_dir",    "EMBEDDINGS_CACHE_DIR"),
        ("vectorstore.url",         "QDRANT_URL"),

        ("vectorstore.collection_name", "QDRANT_COLLECTION_NAME"),
        ("vectorstore.use_sparse",  "QDRANT_USE_SPARSE"),
        ("retriever.top_k",         "RETRIEVER_TOP_K"),
        ("retriever.search_type",   "RETRIEVER_SEARCH_TYPE"),
        ("reranker.enabled",        "RERANKER_ENABLED"),
        ("reranker.top_k",          "RERANKER_TOP_K"),
        ("logging.level",           "LOG_LEVEL"),
        ("logging.json_output",     "LOG_JSON_OUTPUT"),
        ("observability.langsmith_enabled", "LANGSMITH_ENABLED"),
        ("memory.short_term_turns", "MEMORY_SHORT_TERM_TURNS"),
        ("memory.long_term_enabled","MEMORY_LONG_TERM_ENABLED"),
        ("cache.query_ttl_seconds", "CACHE_QUERY_TTL_SECONDS"),
    ]

    def _get_nested(d: dict, path: str):
        keys = path.split(".")
        for k in keys:
            if not isinstance(d, dict) or k not in d:
                return None
            d = d[k]
        return d

    for yaml_path, env_key in mappings:
        if os.environ.get(env_key) is None:
            value = _get_nested(cfg, yaml_path)
            if value is not None:
                os.environ[env_key] = str(value)

@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    _apply_yaml_overrides()
    return AppSettings()

settings = get_settings()

