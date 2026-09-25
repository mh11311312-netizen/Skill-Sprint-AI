from flask import Blueprint, render_template, request, Response, abort
from database.db import get_db
from security.auth import roles_required
from src.reports import REPORTS, build, to_csv, to_xlsx, to_pdf
from src.routes.helpers import STAFF

bp = Blueprint("reports", __name__, url_prefix="/reports")


@bp.route("/")
@roles_required(*STAFF)
def index():
    kind = request.args.get("type", "employee_progress")
    if kind not in REPORTS:
        abort(404)
    rows = build(get_db(), kind)
    return render_template("reports.html", reports=REPORTS, kind=kind, rows=rows[:300], total=len(rows))


@bp.route("/export")
@roles_required(*STAFF)
def export():
    kind, fmt = request.args.get("type", "employee_progress"), request.args.get("fmt", "csv")
    if kind not in REPORTS:
        abort(404)
    rows = build(get_db(), kind)
    name = f"skillsprint_{kind}"
    if fmt == "xlsx":
        return Response(to_xlsx(rows, REPORTS[kind]), mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f"attachment; filename={name}.xlsx"})
    if fmt == "pdf":
        return Response(to_pdf(rows, REPORTS[kind]), mimetype="application/pdf",
                        headers={"Content-Disposition": f"attachment; filename={name}.pdf"})
    return Response(to_csv(rows), mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename={name}.csv"})
