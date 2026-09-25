import re
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from database.db import get_db
from security.auth import roles_required
from role_matrix.builder import rebuild_matrix, matrix_for_role
from role_matrix.extractor import stage_index
from src.audit import now, log_audit
from src.routes.helpers import STAFF, EDITORS

bp = Blueprint("roles", __name__, url_prefix="/roles")


@bp.route("/", methods=["GET", "POST"])
@roles_required(*STAFF)
def index():
    db = get_db()
    if request.method == "POST":
        from flask import session
        if session.get("app_role") not in EDITORS:
            abort(403)
        name = request.form["name"].strip()
        if not name or db.roles.find_one({"name": {"$regex": f"^{re.escape(name)}$", "$options": "i"}}):
            flash("Role name is empty or already exists.", "danger")
        else:
            n = db.roles.count_documents({}) + 1
            rid = f"ROLE-{n:02d}"
            while db.roles.find_one({"role_id": rid}):
                n += 1; rid = f"ROLE-{n:02d}"
            db.roles.insert_one({"role_id": rid, "name": name, "department": request.form.get("department", ""),
                                 "default_level": request.form.get("default_level", "Beginner"),
                                 "description": request.form.get("description", ""), "created_at": now()})
            log_audit("create_role", "role", name)
            s = rebuild_matrix(db)
            count = db.requirements.count_documents({"roles": name, "active": True, "role_scope": "Role-Specific"})
            flash(f"Role '{name}' added. Matrix rebuilt: {count} role-specific requirement(s) found for it in the documents.", "success")
        return redirect(url_for("roles.index"))
    roles = []
    for r in db.roles.find().sort("role_id", 1):
        reqs = matrix_for_role(db, r["name"])
        roles.append({**r, "total": len(reqs), "mandatory": sum(x["obligation"] == "Mandatory" for x in reqs),
                      "specific": sum(x["role_scope"] == "Role-Specific" for x in reqs),
                      "employees": db.employees.count_documents({"role": r["name"]})})
    return render_template("roles.html", roles=roles)


@bp.route("/<name>")
@roles_required(*STAFF)
def detail(name):
    db = get_db()
    role = db.roles.find_one({"name": name}) or abort(404)
    reqs = sorted(matrix_for_role(db, name), key=lambda r: (stage_index(r["due_stage"]), r["document_id"]))
    emps = list(db.employees.find({"role": name}))
    plans = list(db.plans.find({"role": name}, {"plan_json": 0}).sort("created_at", -1))
    by_stage, by_doc = {}, {}
    for r in reqs:
        by_stage[r["due_stage"]] = by_stage.get(r["due_stage"], 0) + 1
        by_doc[r["document_id"]] = by_doc.get(r["document_id"], 0) + 1
    return render_template("role_detail.html", role=role, reqs=reqs, emps=emps, plans=plans,
                           by_stage=by_stage, by_doc=by_doc)
