"""Audit trail: every important action is recorded and never overwritten."""
from datetime import datetime, timezone
from flask import session
from database.db import get_db


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def log_audit(action, entity, entity_id, before=None, after=None, comment="", user=None):
    get_db().audit_log.insert_one({
        "action": action, "entity": entity, "entity_id": entity_id,
        "before": before, "after": after, "comment": comment,
        "user": user or session.get("username", "system"), "at": now(),
    })


def log_security(event, detail, severity="Medium", document_id=None):
    get_db().security_events.insert_one({
        "event": event, "detail": detail, "severity": severity,
        "document_id": document_id, "user": session.get("username", "system"), "at": now(),
    })
