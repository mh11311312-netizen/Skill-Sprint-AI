import re
import os
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, session, abort
from database.db import get_db
from security.auth import roles_required
from document_processing.ingest import ingest, IngestError
from document_validation.validator import CATEGORIES
from src.routes.helpers import STAFF, EDITORS

bp = Blueprint("documents", __name__, url_prefix="/documents")


@bp.route("/")
@roles_required(*STAFF)
def index():
    db = get_db()
    q = {}
    for f in ("category", "status", "trust", "department"):
        if request.args.get(f):
            q[f] = request.args[f]
    if request.args.get("search"):
        q["$or"] = [{"title": {"$regex": re.escape(request.args["search"]), "$options": "i"}},
                    {"document_id": {"$regex": re.escape(request.args["search"]), "$options": "i"}}]
    docs = list(db.documents.find(q).sort([("document_id", 1), ("version_num", -1)]))
    departments = sorted({d["department"] for d in db.documents.find({}, {"department": 1})})
    return render_template("documents.html", docs=docs, categories=CATEGORIES, departments=departments)


@bp.route("/upload", methods=["POST"])
@roles_required(*EDITORS)
def upload():
    files = request.files.getlist("files")
    if not files or not files[0].filename:
        flash("Choose at least one file.", "warning")
        return redirect(url_for("documents.index"))
    form_meta = {k: request.form.get(k, "") for k in ("document_id", "title", "category", "department", "version",
                                                        "effective_date", "review_date", "owner")}
    if len(files) > 1:
        form_meta = {k: "" for k in form_meta}          # batch upload uses embedded metadata only
    db = get_db()
    for f in files:
        data = f.read()
        try:
            doc, summary, impact = ingest(db, f.filename, data, form_meta, current_app.config, session["username"])
            with open(os.path.join(current_app.config["UPLOAD_FOLDER"], f"{doc['doc_key'].replace('@', '_v')}.{doc['file_type']}"), "wb") as out:
                out.write(data)
            msg = f"{f.filename}: stored as {doc['document_id']} v{doc['version']} ({doc['status']}, {doc['trust']}), {doc['chunk_count']} sections."
            if doc["security_flags"]:
                msg += f" {len(doc['security_flags'])} security flag(s) - content quarantined."
            flash(msg, "success" if doc["trust"] == "Trusted" else "warning")
            for w in doc["warnings"]:
                flash(f"{doc['document_id']}: {w}", "info")
            if impact and impact["plans"]:
                flash(f"Policy update: {len(impact['plans'])} onboarding plan(s) are now Outdated. See Impact Analysis.", "warning")
        except IngestError as e:
            for err in e.errors:
                flash(f"{f.filename}: {err}", "danger")
    return redirect(url_for("documents.index"))


@bp.route("/<doc_key>")
@roles_required(*STAFF)
def detail(doc_key):
    db = get_db()
    doc = db.documents.find_one({"doc_key": doc_key}) or abort(404)
    chunks = list(db.chunks.find({"document_id": doc["document_id"], "version": doc["version"]}))
    versions = list(db.documents.find({"document_id": doc["document_id"]}).sort("version_num", -1))
    reqs = {r["requirement_id"]: r for r in db.requirements.find({"document_id": doc["document_id"]})} if doc["status"] == "Active" else {}
    return render_template("document_detail.html", doc=doc, chunks=chunks, versions=versions, reqs=reqs)
