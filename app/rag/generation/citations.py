from __future__ import annotations
import re
from dataclasses import dataclass
from app.rag.retrieval.retriever import RetrievedChunk

@dataclass
class Citation:
    index: int
    filename: str
    page_number: int | None
    chunk_id: str
    document_id: str
    snippet: str

def extract_citations(
    answer: str,
    chunks: list[RetrievedChunk],
) -> tuple[str, list[Citation]]:
    citations: list[Citation] = []
    citation_map: dict[str, int] = {}
    pattern = r'\[Fonte\s*(\d+):\s*([^\],]+?)(?:,\s*p\.(\d+))?\]'

    def replace_citation( match: re.Match ) -> str:
        source_idx = int(match.group(1)) - 1
        filename = match.group(2).strip()
        page = int(match.group(3)) if match.group(3) else None
        chunk = None
        if 0 <=  source_idx < len(chunks):
            chunk = chunks[source_idx]
        else:
            for c in chunks:
                if c.filename == filename:
                    chunk = c
                    break
        if not chunk:
            return match.group(0)

        key = f"{chunk.document_id}:{chunk.chunk_index}"
        if key not in citation_map:
            idx = len(citations) + 1
            citation_map[key] = idx
            citations.append( Citation(
                index=idx,
                filename=chunk.filename,
                page_number=page or chunk.page_number,
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                snippet=chunk.text[:200],
            ) )
        else:
            idx = citation_map[key]
        return f"[{idx}]"

    answer_clean = re.sub(pattern, replace_citation, answer)
    return answer_clean, citations

def format_citations_markdown(citations: list[Citation]) -> str:
    if not citations:
        return ""
    lines = ["\n\n---\n**Fonti:**"]
    for c in citations:
        page_info = f", p. {c.page_number}" if c.page_number else ""
        lines.append(f"[{c.index}] {c.filename}{page_info}")
    return "\n".join(lines)

