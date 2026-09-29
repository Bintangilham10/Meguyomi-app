import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import require_authenticated_user
from app.db.base import Base
from app.db.session import get_db
from app.main import app


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    def database():
        with sessions() as session:
            yield session
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[require_authenticated_user] = lambda: "owner"
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
    engine.dispose()


def test_bank_api_requires_authentication():
    with TestClient(app) as client:
        assert client.get("/memory").status_code == 401
        assert client.get("/memory/export").status_code == 401
        assert client.post("/memory/import", json=[]).status_code == 401


def test_bank_edit_export_import_and_delete_roundtrip(client):
    entry = {"source_text": "\u3053\u3093\u306b\u3061\u306f", "translated_text": "Halo", "category": "verified"}
    created = client.post("/memory", json=entry)
    assert created.status_code == 200
    row_id = created.json()["id"]
    edited = client.post("/memory", json={**entry, "translated_text": "Selamat siang"})
    assert edited.json()["id"] == row_id
    assert client.get("/memory", params={"q": "Selamat"}).json()["total"] == 1
    exported = client.get("/memory/export").json()
    assert exported[0]["category"] == "verified"
    assert client.delete(f"/memory/{row_id}").status_code == 204
    assert client.get("/memory").json()["total"] == 0
    assert client.post("/memory/import", json=exported).json()["imported"] == 1
    assert client.get("/memory").json()["data"][0]["translated_text"] == "Selamat siang"


def test_import_is_validated_atomically_and_preserves_manual_corrections(client):
    source = "\u3042\u308a\u304c\u3068\u3046"
    entry = {"source_text": source, "translated_text": "Terima kasih"}
    assert client.post("/memory", json=entry).status_code == 200
    machine = {**entry, "translated_text": "Wrong", "category": "machine", "model_version": "old"}
    assert client.post("/memory/import", json=[machine]).status_code == 200
    assert client.get("/memory").json()["data"][0]["translated_text"] == "Terima kasih"
    assert client.post("/memory/import", json=[entry, {**entry, "source_text": " "}]).status_code == 422
    assert client.get("/memory").json()["total"] == 1


def test_bank_search_does_not_treat_sql_wildcards_as_user_patterns(client):
    client.post("/memory", json={"source_text": "abc", "translated_text": "Halo"})
    assert client.get("/memory", params={"q": "%"}).json()["total"] == 0


def test_import_rejects_unicode_expansion_before_writing_any_entries(client):
    valid = {"source_text": "\u3042\u308a\u304c\u3068\u3046", "translated_text": "Terima kasih"}
    expanded = {"source_text": "\u337f" * 300, "translated_text": "Perusahaan"}
    assert client.post("/memory", json=expanded).status_code == 422
    assert client.post("/memory/import", json=[valid, expanded]).status_code == 422
    assert client.get("/memory").json()["total"] == 0


def test_chinese_bank_filters_suggestions_and_roundtrips_languages(client):
    source = "\u5927\u4e08\u592b"
    for language, target in [("ja", "Tidak apa-apa"), ("zh-Hans", "Pria sejati"), ("zh-Hant", "Lelaki sejati")]:
        response = client.post("/memory", json={"source_text": source, "translated_text": target, "source_language": language})
        assert response.status_code == 200
    assert client.get("/memory").json()["total"] == 3
    for language in ["ja", "zh-Hans", "zh-Hant"]:
        query = {"source_language": language}
        listing = client.get("/memory", params=query).json()
        assert listing["total"] == 1
        assert listing["data"][0]["source_language"] == language
        suggestions = client.get("/memory/suggestions", params={**query, "q": source}).json()["data"]
        assert len(suggestions) == 1 and suggestions[0]["source_language"] == language
        exported = client.get("/memory/export", params=query).json()
        assert len(exported) == 1 and exported[0]["source_language"] == language
    exported = client.get("/memory/export").json()
    for row in client.get("/memory").json()["data"]:
        client.delete(f"/memory/{row['id']}")
    assert client.post("/memory/import", json=exported).status_code == 200
    assert client.get("/memory").json()["total"] == 3
    assert client.get("/memory", params={"source_language": "en"}).status_code == 422
    assert client.post("/memory/import", json=[{"source_text": source, "translated_text": "Bad", "source_language": "en"}]).status_code == 422
