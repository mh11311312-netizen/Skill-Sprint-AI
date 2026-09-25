"""Shared test setup: in-memory MongoDB (mongomock) and the Sitara Bank sample pack."""
import glob
import os
import sys
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
PACK = os.path.join(ROOT, "sample_documents", "Sitara_Bank_Company_Pack", "documents")

from app import create_app                      # noqa: E402
from database.db import get_db                  # noqa: E402
from src.seed import seed                       # noqa: E402
from document_processing.ingest import ingest   # noqa: E402
from genai_pipeline.client import set_client_override  # noqa: E402


def pack_files():
    return (sorted(glob.glob(f"{PACK}/active/docx/*.docx")) + sorted(glob.glob(f"{PACK}/superseded/pdf/*.pdf"))
            + sorted(glob.glob(f"{PACK}/adversarial/pdf/*.pdf")))


@pytest.fixture(scope="session")
def app():
    app = create_app({"USE_MONGOMOCK": True, "TESTING": True, "WTF_CSRF_ENABLED": False, "MONGO_DB": "test_skillsprint"})
    with app.test_request_context():
        db = get_db()
        seed(db)
        for f in pack_files():
            ingest(db, os.path.basename(f), open(f, "rb").read(), {}, app.config, "pytest")
    yield app
    set_client_override(None)


@pytest.fixture()
def ctx(app):
    with app.test_request_context():
        yield get_db()


@pytest.fixture()
def client(app):
    return app.test_client()


def login(client, username, password):
    client.get("/logout")
    return client.post("/login", data={"username": username, "password": password})
