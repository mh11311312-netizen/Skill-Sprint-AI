"""MongoDB connection. Every module gets the database through get_db()."""
from flask import current_app
from pymongo import MongoClient, ASCENDING

COLLECTIONS = ["users", "roles", "employees", "documents", "chunks", "requirements", "conflicts",
               "plans", "generation_logs", "progress", "audit_log", "security_events", "matrix_builds"]


def init_db(app):
    if app.config.get("USE_MONGOMOCK"):
        import mongomock                       # in-memory database, used only by tests
        client = mongomock.MongoClient()
    else:
        client = MongoClient(app.config["MONGO_URI"], serverSelectionTimeoutMS=8000)
    db = client[app.config["MONGO_DB"]]
    app.extensions["mongo_db"] = db
    _create_indexes(db)
    return db


def _create_indexes(db):
    db.users.create_index([("username", ASCENDING)], unique=True)
    db.roles.create_index([("name", ASCENDING)], unique=True)
    db.employees.create_index([("employee_id", ASCENDING)], unique=True)
    db.documents.create_index([("doc_key", ASCENDING)], unique=True)
    db.documents.create_index([("file_hash", ASCENDING)])
    db.chunks.create_index([("document_id", ASCENDING), ("version", ASCENDING)])
    db.requirements.create_index([("requirement_id", ASCENDING)])
    db.plans.create_index([("plan_id", ASCENDING)], unique=True)


def get_db():
    return current_app.extensions["mongo_db"]
