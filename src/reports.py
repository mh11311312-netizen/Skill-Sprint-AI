"""Steps 62/63 - Reports and export (CSV, Excel, PDF)."""
import csv
import io
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
from src.progress import assess

REPORTS = {
    "employee_progress": "Employee progress",
    "role_coverage": "Role coverage",
    "mandatory_training": "Mandatory training",
    "assessment_results": "Assessment results",
    "source_traceability": "Source traceability",
    "hallucination_flags": "Hallucination flags",
    "policy_coverage": "Policy coverage",
    "genai_python_comparison": "GenAI / Python comparison",
}


def _latest_plans(db):
    plans = {}
    for p in db.plans.find().sort("created_at", 1):
        plans[p["employee_id"]] = p
    return list(plans.values())


def build(db, kind):
    rows = []
    if kind == "employee_progress":
        for p in _latest_plans(db):
            e = db.employees.find_one({"employee_id": p["employee_id"]}) or {}
            a = assess(db, p, e)
            rows.append({"Employee": p["employee_id"], "Name": e.get("full_name", ""), "Role": p["role"],
                         "Plan": p["plan_id"], "Plan status": p["status"], "Overall %": a["overall"],
                         "Modules %": a["module_pct"], "Quiz avg": a["quiz_avg"], "Progress status": a["status"],
                         "Overdue modules": ", ".join(a["overdue"])})
    elif kind == "role_coverage":
        for r in db.roles.find().sort("role_id", 1):
            reqs = list(db.requirements.find({"roles": r["name"], "active": True}))
            plans = [p for p in db.plans.find({"role": r["name"]}) if p.get("validation")]
            avg = lambda k: round(sum(p["validation"]["scores"][k] for p in plans) / len(plans), 1) if plans else ""
            rows.append({"Role": r["name"], "Requirements": len(reqs),
                         "Mandatory": sum(x["obligation"] == "Mandatory" for x in reqs),
                         "Plans validated": len(plans), "Avg coverage %": avg("coverage"),
                         "Avg traceability %": avg("traceability"),
                         "Verified plans": sum(p["validation"]["status"] == "Verified" for p in plans)})
    elif kind == "mandatory_training":
        for p in _latest_plans(db):
            prog = db.progress.find_one({"plan_id": p["plan_id"]}) or {"modules_done": {}}
            for m in p["plan_json"]["modules"]:
                if m["mandatory"]:
                    rows.append({"Employee": p["employee_id"], "Role": p["role"], "Module": m["module_id"],
                                 "Title": m["module_title"], "Stage": m["stage"],
                                 "Completed": "Yes" if m["module_id"] in prog["modules_done"] else "No"})
    elif kind == "assessment_results":
        for prog in db.progress.find():
            for a in prog.get("quiz_attempts", []):
                rows.append({"Employee": prog["employee_id"], "Plan": prog["plan_id"], "Module": a["module_id"],
                             "Score %": a["score"], "Correct": a["correct"], "Total": a["total"], "At": a["at"]})
    elif kind == "source_traceability":
        for p in db.plans.find({"validation": {"$exists": True}}):
            s = p["validation"]["scores"]
            rows.append({"Plan": p["plan_id"], "Role": p["role"], "Traceability %": s["traceability"],
                         "Mandatory traceability %": s["mandatory_traceability"], "Coverage %": s["coverage"],
                         "Validation status": p["validation"]["status"]})
    elif kind == "hallucination_flags":
        for p in db.plans.find({"validation": {"$exists": True}}):
            for i in p["validation"]["issues"]:
                if i["kind"] in ("Possible hallucination", "Unsupported fact", "Traceability", "Security"):
                    rows.append({"Plan": p["plan_id"], "Role": p["role"], "Kind": i["kind"], "Severity": i["severity"],
                                 "Where": i["where"], "Message": i["message"]})
            for r in p["validation"]["rows"]:
                if r["status"] in ("Unsupported Requirement", "Source Support Missing"):
                    rows.append({"Plan": p["plan_id"], "Role": p["role"], "Kind": r["status"], "Severity": "High",
                                 "Where": r["requirement_id"], "Message": r["explanation"]})
    elif kind == "policy_coverage":
        cites = {}
        for p in db.plans.find():
            for m in p["plan_json"]["modules"]:
                for rc in m.get("requirements_covered", []):
                    cites[rc["source_document_id"]] = cites.get(rc["source_document_id"], 0) + 1
        for d in db.documents.find({"status": "Active"}).sort("document_id", 1):
            reqs = db.requirements.count_documents({"document_id": d["document_id"], "active": True})
            rows.append({"Document": d["document_id"], "Title": d["title"], "Version": d["version"],
                         "Category": d["category"], "Trust": d["trust"], "Active requirements": reqs,
                         "Times cited in plans": cites.get(d["document_id"], 0)})
    elif kind == "genai_python_comparison":
        for p in db.plans.find({"validation": {"$exists": True}}):
            for r in p["validation"]["rows"]:
                py, ge = r.get("python") or {}, r.get("genai") or {}
                match = "Match" if r["status"] == "Verified" else ("Mismatch" if r["status"] != "Optional Not Included" else "-")
                rows.append({"Plan": p["plan_id"], "Requirement ID": r["requirement_id"], "Role": r["role"],
                             "Source": py.get("source") or ge.get("source", ""),
                             "Python expected": f"{'Mandatory' if py.get('mandatory') else 'Optional'} / {py.get('due_stage','')}" if py else "Not in matrix",
                             "GenAI result": f"{'Mandatory' if ge.get('mandatory') else 'Optional'} / {ge.get('due_stage','')}" if ge else "Not generated",
                             "Match/Mismatch": match,
                             "Coverage status": "Covered" if ge else "Missing",
                             "Traceability status": r.get("source_check", ""),
                             "Validation status": r["status"], "Explanation": r["explanation"]})
    return rows


def to_csv(rows):
    buf = io.StringIO()
    if rows:
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    else:
        buf.write("No data\n")
    return buf.getvalue().encode("utf-8-sig")


def to_xlsx(rows, title):
    buf = io.BytesIO()
    sheet = "".join(ch for ch in title if ch not in '[]:*?/\\')[:30]
    pd.DataFrame(rows or [{"Info": "No data"}]).to_excel(buf, index=False, sheet_name=sheet, engine="openpyxl")
    return buf.getvalue()


def to_pdf(rows, title):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=20, rightMargin=20, topMargin=24, bottomMargin=24)
    ss = getSampleStyleSheet()
    small = ss["BodyText"].clone("small", fontSize=7, leading=8.5)
    story = [Paragraph(f"SkillSprint AI - {title}", ss["Title"]), Spacer(1, 6)]
    if rows:
        cols = list(rows[0].keys())
        data = [[Paragraph(f"<b>{c}</b>", small) for c in cols]]
        for r in rows[:1500]:
            data.append([Paragraph(str(r[c]).replace("&", "&amp;").replace("<", "&lt;")[:300], small) for c in cols])
        t = Table(data, repeatRows=1)
        t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                               ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DDE7E3")),
                               ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story.append(t)
    else:
        story.append(Paragraph("No data.", ss["BodyText"]))
    doc.build(story)
    return buf.getvalue()
