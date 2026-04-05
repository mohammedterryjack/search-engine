from __future__ import annotations

from app.main import vector_health
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
