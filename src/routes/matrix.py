from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from database.db import get_db
from security.auth import roles_required
from role_matrix.builder import rebuild_matrix
from role_matrix.extractor import stage_index
from src.routes.helpers import STAFF, EDITORS

bp = Blueprint("matrix", __name__, url_prefix="/matrix")


@bp.route("/")
@roles_required(*STAFF)
def index():
    db = get_db()
    q = {}
    if request.args.get("role"):
        q["roles"] = request.args["role"]
    for f in ("document_id", "obligation", "priority", "due_stage", "role_scope"):
        if request.args.get(f):
            q[f] = request.args[f]
    if request.args.get("active", "yes") == "yes":
        q["active"] = True
    reqs = sorted(db.requirements.find(q), key=lambda r: (r["document_id"], [int(x) for x in r["section_id"].split(".") if x.isdigit()]))
    build = db.matrix_builds.find_one(sort=[("built_at", -1)])
    return render_template("matrix.html", reqs=reqs, build=build,
                           roles=list(db.roles.find().sort("role_id", 1)),
                           doc_ids=sorted(db.requirements.distinct("document_id")))


@bp.route("/rebuild", methods=["POST"])
@roles_required(*EDITORS)
def rebuild():
    s = rebuild_matrix(get_db(), session["username"])
    flash(f"Matrix rebuilt: {s['active']} active requirements ({s['mandatory']} mandatory), "
          f"{s['conflicts']} source conflicts, {s['duplicates']} duplicates.", "success")
    return redirect(url_for("matrix.index"))


@bp.route("/conflicts")
@roles_required(*STAFF)
def conflicts():
    db = get_db()
    items = list(db.conflicts.find())
    return render_template("conflicts.html",
                           conflicts=[c for c in items if c["kind"] == "conflict"],
                           duplicates=[c for c in items if c["kind"] == "duplicate"],
                           missing=[c for c in items if c["kind"] == "missing_reference"],
                           unmapped=[c for c in items if c["kind"] == "unmapped_role"],
                           review=list(db.requirements.find({"conflict_review": True})))
