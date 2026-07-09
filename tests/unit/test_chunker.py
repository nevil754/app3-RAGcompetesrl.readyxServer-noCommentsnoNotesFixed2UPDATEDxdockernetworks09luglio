import pytest
from app.rag.ingestion.chunker import chunk_document
from app.rag.ingestion.cleaner import clean_text

class TestCleaner:
    def test_removes_null_bytes(self):
        dirty = "testo\x00pulito"
        assert "\x00" not in clean_text(dirty)

    def test_collapses_multiple_newlines(self):
        text = "paragrafo 1\n\n\n\n\nparagrafo 2"
        result = clean_text(text)
        assert "\n\n\n" not in result

    def test_removes_page_numbers(self):
        text = "testo\n- 42 -\naltro testo"
        result = clean_text(text)
        assert "- 42 -" not in result

    def test_empty_string(self):
        assert clean_text("") == ""

    def test_preserves_content(self):
        text = "Il contratto scade il 31/12/2024"
        assert clean_text(text) == text

class TestChunker:
    def test_basic_chunking(self):
        text = "A" * 3000
        chunks = chunk_document(text)
        assert len(chunks) > 1
        assert all(len(c.text) <= 1200 for c in chunks)

    def test_minimum_chunk_size(self):
        text = "Ciao"
        chunks = chunk_document(text)

        assert len(chunks) == 0 or all(len(c.text) >= 50 for c in chunks)

    def test_chunk_has_index(self):
        text = "Paragrafo " * 200
        chunks = chunk_document(text)
        for i, chunk in enumerate(chunks):
            assert chunk.chunk_index == i

    def test_metadata_inherited(self):
        text = "Testo " * 300
        meta = {"document_id": "test-123"}
        chunks = chunk_document(text, base_metadata=meta)
        for chunk in chunks:
            assert chunk.metadata.get("document_id") == "test-123"

class TestContextBuilder:
    def test_format_sources(self, sample_chunks):
        from app.rag.memory.context_builder import format_sources_for_response
        sources = format_sources_for_response(sample_chunks)
        assert len(sources) == 2
        assert sources[0]["filename"] == "contratto_acme.pdf"
        assert sources[0]["page_number"] == 3
        assert "score" in sources[0]

    def test_build_context_limits_chars(self, sample_chunks):
        from app.rag.memory.context_builder import build_rag_context
        ctx = build_rag_context(
            chunks=sample_chunks,
            session_messages=[],
            max_context_chars=100,
        )

        assert len(ctx["context"]) <= 300

    def test_empty_history(self, sample_chunks):
        from app.rag.memory.context_builder import build_rag_context
        ctx = build_rag_context(chunks=sample_chunks, session_messages=[])
        assert ctx["history"] == "Nessuna conversazione precedente."

    def test_history_formatted(self, sample_chunks):
        from app.rag.memory.context_builder import build_rag_context
        messages = [
            {"role": "user", "content": "Ciao"},
            {"role": "assistant", "content": "Salve"},
        ]
        ctx = build_rag_context(chunks=sample_chunks, session_messages=messages)
        assert "Utente: Ciao" in ctx["history"]
        assert "Assistente: Salve" in ctx["history"]

