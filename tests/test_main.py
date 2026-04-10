from __future__ import annotations

import json

from app.main import _serialize_search_results, summarizer_health, vector_health
from app.models import SearchResult
from app.services.vector_store import VectorStoreError


def test_vector_health_reports_ok(monkeypatch) -> None:
    class DummySettings:
        enable_vector_retrieval = True
        vector_model_name = "sentence-transformers/all-MiniLM-L6-v2"

    class DummyModel:
        device = "cpu"

    monkeypatch.setattr("app.main.settings", DummySettings())
    monkeypatch.setattr("app.main.get_embedding_model", lambda: DummyModel())

    health = vector_health()

    assert health == {
        "status": "ok",
        "model_name": "sentence-transformers/all-MiniLM-L6-v2",
        "device": "cpu",
    }


def test_vector_health_reports_error(monkeypatch) -> None:
    class DummySettings:
        enable_vector_retrieval = True
        vector_model_name = "sentence-transformers/all-MiniLM-L6-v2"

    monkeypatch.setattr("app.main.settings", DummySettings())
    monkeypatch.setattr(
        "app.main.get_embedding_model",
        lambda: (_ for _ in ()).throw(VectorStoreError("bad cache")),
    )

    health = vector_health()

    assert health == {
        "status": "error",
        "model_name": "sentence-transformers/all-MiniLM-L6-v2",
        "error": "bad cache",
    }


def test_vector_health_reports_disabled(monkeypatch) -> None:
    class DummySettings:
        enable_vector_retrieval = False
        vector_model_name = "sentence-transformers/all-MiniLM-L6-v2"

    monkeypatch.setattr("app.main.settings", DummySettings())

    health = vector_health()

    assert health == {
        "status": "disabled",
        "model_name": "sentence-transformers/all-MiniLM-L6-v2",
    }


def test_summarizer_health_uses_service_health_endpoint(monkeypatch) -> None:
    class DummySettings:
        enable_summarizer = True
        summarizer_model = "Falconsai/text_summarization"
        summarizer_url = "http://summariser:8020"

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps(
                {"status": "healthy", "model": "Falconsai/text_summarization"}
            ).encode("utf-8")

    captured = {}

    def fake_urlopen(request, timeout=2):
        captured["url"] = request.full_url
        return FakeResponse()

    monkeypatch.setattr("app.main.settings", DummySettings())
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    health = summarizer_health()

    assert captured["url"] == "http://summariser:8020/health"
    assert health == {
        "status": "ok",
        "model_name": "Falconsai/text_summarization",
        "url": "http://summariser:8020",
    }


def test_serialize_search_results_returns_public_api_shape() -> None:
    results = [
        SearchResult(
            source_root_id=1,
            source_path="/source/root",
            document_id=7,
            content_unit_id=9,
            document_path="/docs/paper.pdf",
            filename="paper.pdf",
            unit_type="section",
            page_number=3,
            section_name="Introduction",
            score=0.87,
            text_content="Full section text",
            image_mime=None,
            image_data=None,
            highlighted_text="<mark>Short</mark> display text",
        )
    ]

    payload = _serialize_search_results(results)

    assert payload == [
        {
            "source_root_id": 1,
            "content_unit_id": 9,
            "unit_type": "section",
            "page_number": 3,
            "section_name": "Introduction",
            "text_content": "Full section text",
            "image_mime": None,
            "image_data": None,
            "highlighted_text": "<mark>Short</mark> display text",
        }
    ]


def test_serialize_search_results_defaults_missing_text_content_to_empty_string() -> None:
    results = [
        SearchResult(
            source_root_id=1,
            source_path="/source/root",
            document_id=7,
            content_unit_id=9,
            document_path="/docs/paper.pdf",
            filename="paper.pdf",
            unit_type="figure",
            page_number=None,
            section_name="Figure 1",
            score=0.42,
            text_content=None,
            image_mime="image/png",
            image_data="abc123",
            highlighted_text=None,
        )
    ]

    payload = _serialize_search_results(results)

    assert payload[0]["text_content"] == ""
    assert "score" not in payload[0]
    assert "source_path" not in payload[0]
    assert "document_id" not in payload[0]
    assert "document_path" not in payload[0]
    assert "display_text" not in payload[0]
    assert "filename" not in payload[0]
    assert payload[0]["highlighted_text"] == ""
