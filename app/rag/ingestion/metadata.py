from __future__ import annotations
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import yaml
from loguru import logger
from app.core.settings import get_settings

settings = get_settings()
_metadata_config: dict | None = None

def build_chunk_metadata(
    tenant_id: str,
    collection_id: str | None,
    document_id: str,
    filename: str,
    chunk_index: int,
    page_number: int | None,
    file_type: str,
    document_text_sample: str = "",
) -> dict[str, Any]:
    doc_type = _classify_document(document_text_sample, filename)
    metadata: dict[str, Any] = {

        "tenant_id": tenant_id,
        "collection_id": collection_id,
        "document_id": document_id,
        "filename": filename,
        "file_type": file_type.lstrip(".").lower(),
        "doc_type": doc_type,

        "chunk_index": chunk_index,
        "page_number": page_number,

        "ingested_at": datetime.now(timezone.utc).isoformat(),
    }
    return metadata

def _classify_document(text_sample: str, filename: str) -> str:
    cfg = get_metadata_config()
    doc_types = cfg.get("document_types", {})
    text_lower = ( text_sample + " " + filename ).lower()
    for doc_type, type_cfg in doc_types.items():
        if doc_type == "generic":
            continue
        keywords = type_cfg.get("detect_keywords", [])
        if any( kw.lower() in text_lower for kw in keywords ):
            logger.debug(f"Documento classificato come: {doc_type}")
            return doc_type

    return "generic"

def get_metadata_config() -> dict:
    global _metadata_config
    if _metadata_config is None:
        config_path = Path(settings.metadata_config_file)
        if config_path.exists():
            with open(config_path) as f:
                _metadata_config = yaml.safe_load(f) or {}
        else:
            _metadata_config = {}
    return _metadata_config

