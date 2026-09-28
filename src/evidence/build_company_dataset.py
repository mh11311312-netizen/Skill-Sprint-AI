"""Deliverable 3 - Company Document Dataset (PDF).
Reads the Sitara Bank pack in sample_documents/ (the same files the application ingests) and compiles the
company profile, scenario, every policy / SOP / role description / FAQ / compliance document, the requirement
matrix, metadata, version history, conflict cases and adversarial cases into one professional PDF.
Run:  python -m src.evidence.build_company_dataset"""
import csv
import glob
import os
import re
import sys
from collections import Counter

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.platypus import NextPageTemplate, PageBreak, Spacer, KeepTogether, CondPageBreak, Paragraph

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from src.evidence.pdfkit import *   # noqa: E402,F401,F403

PACK = os.path.join(ROOT, "sample_documents", "Sitara_Bank_Company_Pack")
OUT = os.path.join(ROOT, "reports", "Deliverable_3_Company_Document_Dataset.pdf")
PW = 174 * mm          # portrait text width
LW = 269 * mm          # landscape text width


def rd(name):
    return list(csv.DictReader(open(os.path.join(PACK, "data", name), encoding="utf-8-sig")))


def front_matter(text):
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    meta = dict(ln.split(": ", 1) for ln in m.group(1).splitlines() if ": " in ln)
    return meta, m.group(2)


def doc_flowables(path, adversarial=False):
    """Turns one markdown source document into styled flowables (metadata box, sections, clauses)."""
    meta, body = front_matter(open(path, encoding="utf-8").read())
    out = [H2(f"{esc(meta['document_id'])}  ·  {esc(meta['title'])}")]
    tagcolor = "#a3372a" if adversarial else "#2b7a53"
    out.append(kv([("Document ID / version", f"{meta['document_id']}  v{meta['version']}"),
                   ("Category · Department", f"{meta['category']}  ·  {meta['department']}"),
                   ("Status · Effective · Review", f"{meta['status']}  ·  {meta['effective_date']}  ·  {meta['review_date']}"),
                   ("Owner · Supersedes", f"{meta['owner']}  ·  {meta.get('supersedes', 'None')}")], widths=(46 * mm, 128 * mm)))
    out.append(Spacer(1, 6))
    if adversarial:
        out.extend(callout("UNTRUSTED TEST DOCUMENT", "This file is an attack sample created to test prompt-injection defences. "
                           "The application must treat it as data, quarantine it, and keep it out of the requirement matrix.", "warn", PW))
    for ln in body.splitlines():
        s = ln.strip()
        if not s or s.startswith("# "):
            continue
        if s.startswith("## "):
            out.append(Paragraph(esc(s[3:]), S["h3"]))
        elif s.startswith("Applies to:"):
            out.append(Paragraph(f"<font color='{tagcolor}'>Applies to:</font> {esc(s[11:].strip())}", S["tag"]))
        else:
            hidden = "<span" in s
            s2 = re.sub(r"</?span[^>]*>", "", s)
            m = re.match(r"^(\d+\.\d+)\s+(.*)$", s2)
            if m:
                flag = (" <font name='Sans-B' size='7' color='#a3372a'>[HIDDEN TEXT: white, 1 pt in the source file]</font>" if hidden else "")
                out.append(Paragraph(f"<font name='Mono-B' color='#c9922e'>{m.group(1)}</font>&nbsp;&nbsp;{esc(m.group(2))}{flag}", S["clause"]))
            else:
                out.append(Paragraph(esc(s2), S["body"]))
    out.append(Spacer(1, 8))
    return out


def cover(c, doc):
    draw_cover(c, doc, "", ["Company Document", "Dataset"],
               "Sitara Bank Ltd. - the fictional organisation, its policies, SOPs, role descriptions, FAQs, compliance documents, "
               "requirement matrix, version history, conflict cases and adversarial cases.",
               [("Deliverable", "3 of 18  -  Company Document Dataset (SRS 1.10)"), ("Organisation", "Sitara Bank Ltd., Karachi (fictional)"),
                ("Project", "SkillSprint AI  -  Training and Onboarding Intelligence"), ("Category", "Generative AI PowerPlay  -  OnboardVerse"),
                ("Document version", "1.0  -  September 2026")], "Deliverable 3")


def build():
    meta = rd("documents_metadata.csv")
    reqs = rd("requirements_master.csv")
    matrix = rd("role_requirement_matrix.csv")
    roles, emps = rd("roles.csv"), rd("employees.csv")
    hist, conf, adv, dup = rd("version_history.csv"), rd("conflict_cases.csv"), rd("adversarial_cases.csv"), rd("duplicate_cases.csv")
    active = [m for m in meta if m["status"] == "Active" and m["is_adversarial"] == "No"]
    superseded = [m for m in meta if m["status"] == "Superseded"]
    adversarial = [m for m in meta if m["is_adversarial"] == "Yes"]
    in_matrix = [r for r in reqs if r["include_in_active_matrix"].strip().lower() in ("yes", "true", "1")]
    mand = [r for r in in_matrix if r["obligation"] == "Mandatory"]
    role_spec = [r for r in in_matrix if r["role_scope"] == "Role-Specific"]
    changes = [h for h in hist if h["change_summary"].strip()]
    print(f"docs active={len(active)} sup={len(superseded)} adv={len(adversarial)} reqs={len(reqs)} in_matrix={len(in_matrix)} "
          f"mandatory={len(mand)} role_specific={len(role_spec)} changes={len(changes)} conflicts={len(conf)} adv_cases={len(adv)}")

    story = [NextPageTemplate("port"), PageBreak(), P("Contents", "h1"), GoldRule(), Spacer(1, 6)]
    toc = make_toc()
    story += [toc, PageBreak()]

    # ---------------- 1 overview ----------------
    story += H1("1. Dataset overview")
    story.append(P("This document is the <b>Company Document Dataset</b> required by SRS Section 1.10, item 3. SkillSprint AI does not ship "
                   "with a ready-made company: the team invented one, wrote its documents, and deliberately planted version changes, "
                   "conflicting statements and attack documents in it so that every requirement of the SRS can be demonstrated. "
                   "Everything in this PDF is compiled directly from the same files that the application ingests "
                   "(<font name='Mono'>sample_documents/Sitara_Bank_Company_Pack/</font>) - nothing is re-typed by hand.", "body"))
    story.append(stat_cards([(len(active), "active documents"), (len(roles), "job roles"), (len(in_matrix), "requirements"),
                             (len(mand), "mandatory"), (len(role_spec), "role-specific")]))
    story.append(Spacer(1, 6))
    story.append(stat_cards([(len(changes), "policy-version changes"), (len(conf), "conflict cases"), (len(adv), "adversarial cases"),
                             (len(superseded), "superseded versions"), (len(emps), "sample employees")]))
    story.append(Spacer(1, 10))
    story.append(P("Compliance with the SRS minimum dataset", "h2"))
    def row(item, need, have):
        return [item, str(need), str(have), "Met" if have >= need else "NOT MET"]
    story.append(table([["SRS minimum", "Required", "This dataset", "Result"],
                        row("Company documents", 20, len(active)), row("Job roles", 10, len(roles)),
                        row("Identifiable policy / process requirements", 150, len(in_matrix)),
                        row("Mandatory requirements", 50, len(mand)), row("Role-specific requirements", 30, len(role_spec)),
                        row("Conflicting or ambiguous document cases", 10, len(conf)), row("Policy-version changes", 10, len(changes)),
                        row("Adversarial / prompt-injection cases", 10, len(adv))],
                       [82 * mm, 26 * mm, 36 * mm, 30 * mm], col_style={3: "cellb"}))
    story.append(Spacer(1, 10))
    story.append(P("What is inside", "h2"))
    story.append(table([["Part", "SRS item", "Content"],
                        ["2", "Company profile, organisational scenario", "Who Sitara Bank is, why it needs SkillSprint, departments, roles, sample employees"],
                        ["3", "Document metadata", f"Register of all {len(meta)} documents: ID, category, version, status, dates, owner, precedence"],
                        ["4-9", "Policies, compliance, SOPs, role descriptions, FAQs", "Full text of every active document, clause by clause, with clause IDs"],
                        ["10", "Requirement matrix", f"All {len(reqs)} identified requirements plus a role-by-role summary of the expanded matrix"],
                        ["11", "Version history", "Every document version, when it was superseded and what changed"],
                        ["12", "Conflict cases", f"{len(conf)} planted contradictions with the precedence rule that resolves each"],
                        ["13", "Adversarial cases", f"{len(adv)} attack cases and the {len(adversarial)//2} attack documents that carry them"]],
                       [16 * mm, 62 * mm, 96 * mm]))

    # ---------------- 2 profile ----------------
    story += H1("2. Company profile and organisational scenario")
    story.append(P("Fictional organisation created for the SkillSprint AI project. All names, figures and rules are invented.", "lead"))
    story.append(kv([("Company", "Sitara Bank Ltd."), ("Industry", "Retail banking"), ("Headquarters", "Karachi, Pakistan"),
                     ("Network", "40 branches in Karachi, Lahore, Islamabad and other cities"), ("Employees", "About 2,500"),
                     ("Core values", "Integrity, Customer First, Accountability, Security"),
                     ("Hiring pace", "About 40 new employees every month")]))
    story.append(P("Organisational scenario", "h2"))
    story.append(P("Sitara Bank is expanding its branch network and hires about 40 new employees every month. Onboarding is currently handled "
                   "manually by HR and branch managers using scattered policies, SOPs and FAQs. Several documents were updated in 2026, but "
                   "older FAQs and handbooks were not revised, so new joiners often receive <b>conflicting instructions</b> (for example on "
                   "leave notice, password rules and complaint escalation times). Regulators expect customer-facing staff to complete AML and "
                   "KYC training quickly and to be able to prove it. The bank wants SkillSprint AI to create personalised, source-traceable "
                   "onboarding plans for every role and to detect outdated, conflicting or unsupported content automatically."))
    story.append(P("Departments", "h2"))
    story.append(P("Retail Banking, Customer Service, Human Resources, Finance, Operations, Information Technology, Compliance, Marketing, "
                   "Data and Analytics."))
    story.append(P("Job roles", "h2"))
    story.append(table([["Role ID", "Role", "Department", "Default level", "Description"]] +
                       [[r["role_id"], r["role"], r["department"], r["default_level"], r["description"]] for r in roles],
                       [17 * mm, 34 * mm, 30 * mm, 21 * mm, 72 * mm]))
    story.append(P("Sample employees", "h2"))
    story.append(P("Fifteen fictional employees, one or more per role. Each has an experience level and joining date that drive plan personalisation.", "small"))
    story.append(table([["ID", "Name", "Role", "Level", "Location", "Joined"]] +
                       [[e["employee_id"], e["full_name"], e["role"], e["experience_level"], e["location"], e["joining_date"]] for e in emps],
                       [16 * mm, 30 * mm, 42 * mm, 22 * mm, 44 * mm, 20 * mm]))
    story.append(P("Document precedence (conflict resolution order)", "h2"))
    story.append(P("When two sources disagree, the higher-authority source wins. This order is stored in <font name='Mono'>config/precedence_rules.yaml</font> "
                   "and applied by Python, never by the language model."))
    story.append(table([["Level", "Category", "Reason"], ["1", "Policy", "Formally approved company rules"], ["2", "Compliance", "Regulatory training requirements"],
                        ["3", "SOP", "Operational procedures derived from policy"], ["4", "Handbook", "General employee guidance"],
                        ["5", "Role Description", "Role-specific duties"], ["6", "Process Manual", "How-to guidance for HR processes"],
                        ["7", "FAQ", "Informal answers, most likely to be outdated"]], [16 * mm, 40 * mm, 118 * mm]))

    # ---------------- 3 metadata ----------------
    story += [NextPageTemplate("land"), PageBreak()]
    story += H1("3. Document metadata register")
    story.append(P(f"All {len(meta)} documents in the pack: {len(active)} active, {len(superseded)} superseded earlier versions kept for history and "
                   f"impact analysis, and {len(adversarial)} adversarial attack documents. Every document exists as PDF, DOCX and Markdown.", "body"))
    rows = [["ID", "Title", "Category", "Department", "Ver", "Status", "Effective", "Review", "Owner", "Supersedes", "Prec."]]
    for m in sorted(meta, key=lambda x: (x["is_adversarial"], x["status"] != "Active", x["document_id"], x["version"])):
        rows.append([m["document_id"], m["title"], m["category"], m["department"], m["version"], m["status"], m["effective_date"],
                     m["review_date"], m["owner"], m["supersedes"], m["precedence_level"]])
    story.append(table(rows, [16 * mm, 62 * mm, 24 * mm, 30 * mm, 10 * mm, 21 * mm, 20 * mm, 20 * mm, 32 * mm, 22 * mm, 12 * mm], pad=3))
    story += [NextPageTemplate("port"), PageBreak()]

    # ---------------- 4-9 documents ----------------
    groups = [("4. Company policies and employee handbook", lambda m: m["category"] in ("Policy", "Handbook"),
               "Formally approved company rules. Policies sit at the top of the precedence order."),
              ("5. Compliance documents", lambda m: m["category"] == "Compliance",
               "Regulatory training requirements that apply across the bank."),
              ("6. Standard Operating Procedures (SOPs)", lambda m: m["category"] == "SOP",
               "Step-by-step procedures for customer service, escalation, KYC, cash handling, IT, payments, marketing and data access."),
              ("7. Role descriptions", lambda m: m["category"] == "Role Description",
               f"Duties, authority limits and training expectations for each of the {len(roles)} roles."),
              ("8. Process manual", lambda m: m["category"] == "Process Manual",
               "How HR runs a new joiner's first weeks."),
              ("9. Frequently asked questions (FAQs)", lambda m: m["category"] == "FAQ",
               "Informal answers. FAQs rank lowest in precedence, and some intentionally contain outdated statements to test conflict handling.")]
    for title, pred, blurb in groups:
        docs = sorted([m for m in active if pred(m)], key=lambda m: m["document_id"])
        story += H1(title)
        story.append(P(blurb + f"  ({len(docs)} document{'s' if len(docs) != 1 else ''}: " + ", ".join(d["document_id"] for d in docs) + ")", "lead"))
        for d in docs:
            path = os.path.join(PACK, d["markdown_file"])
            story.append(CondPageBreak(70 * mm))
            story.extend(doc_flowables(path))

    # ---------------- 10 requirement matrix ----------------
    story += [NextPageTemplate("land"), PageBreak()]
    story += H1("10. Requirement matrix")
    story.append(P(f"The <b>Role Requirement Matrix</b> lists every identifiable policy or process requirement found in the active documents. "
                   f"{len(reqs)} requirements were identified; {len(in_matrix)} are active in the matrix, and the rest are duplicates or lost a "
                   f"precedence conflict (marked below). The table shows the master list; the application expands it into a role-by-role matrix of "
                   f"{len(matrix):,} rows (<font name='Mono'>data/role_requirement_matrix.csv</font>).", "body"))
    by_role = Counter()
    mand_role = Counter()
    for r in matrix:
        by_role[r["role"]] += 1
        if r["obligation"] == "Mandatory":
            mand_role[r["role"]] += 1
    story.append(P("Role-by-role summary of the expanded matrix", "h2"))
    obl = {}
    for r in matrix:
        obl.setdefault(r["role"], Counter())[r["obligation"]] += 1
    story.append(table([["Role", "Requirements", "Mandatory", "Recommended", "Optional"]] +
                       [[ro["role"], by_role[ro["role"]], obl[ro["role"]]["Mandatory"], obl[ro["role"]]["Recommended"], obl[ro["role"]]["Optional"]] for ro in roles],
                       [70 * mm, 40 * mm, 40 * mm, 40 * mm, 40 * mm]))
    story.append(CondPageBreak(95 * mm))
    story.append(P("Master requirement list", "h2"))
    story.append(P("Obligation is taken from the wording: <b>must / shall / required</b> = Mandatory, <b>should</b> = Recommended, <b>may</b> = Optional. "
                   "Status shows whether a requirement is active, a duplicate of another, or overruled by a higher-precedence source.", "small"))
    rows = [["Req ID", "Requirement", "Obligation", "Type", "Applies to", "Priority", "Due stage", "Assessment", "Status"]]
    for r in reqs:
        roles_txt = r["applicable_roles"]
        if r["role_scope"] != "Role-Specific":
            roles_txt = "All roles" if len(roles_txt.split(";")) >= 11 else roles_txt
        status = "Active" if r["include_in_active_matrix"].strip().lower() in ("yes", "true", "1") else (
            f"Duplicate of {r['duplicate_of']}" if r["duplicate_of"] else (r["conflict_status"] or "Inactive"))
        rows.append([f"<font name='Mono' size='7'>{esc(r['requirement_id'])}</font>", r["requirement_text"], r["obligation"], r["requirement_type"],
                     roles_txt, r["priority"], r["due_stage"], r["assessment_requirement"], status])
    story.append(table(rows, [24 * mm, 86 * mm, 19 * mm, 24 * mm, 36 * mm, 17 * mm, 20 * mm, 25 * mm, 18 * mm], pad=3))

    # ---------------- 11-13 cases ----------------
    story += H1("11. Version history")
    story.append(P(f"{len(changes)} policy-version changes across {len({h['document_id'] for h in hist})} documents. Only the Active version is used to build the "
                   "requirement matrix; earlier versions are kept so the application can show which plans and quiz questions a policy update affects.", "body"))
    story.append(table([["Document", "Ver", "Status", "Effective", "Superseded on", "Superseded by", "Changed sections", "What changed"]] +
                       [[h["document_id"], h["version"], h["status"], h["effective_date"], h["superseded_on"] or "-", h["superseded_by"] or "-",
                         h["changed_sections"], h["change_summary"] or "(earlier version)"] for h in hist],
                       [20 * mm, 10 * mm, 21 * mm, 20 * mm, 22 * mm, 24 * mm, 22 * mm, 130 * mm], pad=3))
    story += H1("12. Conflict cases")
    story.append(P(f"{len(conf)} deliberately planted contradictions. For each, the expected behaviour is decided by the documented precedence order - "
                   "the application must reproduce it without any code change.", "body"))
    story.append(table([["Case", "Type", "Statement A", "Statement B", "Precedence rule", "Prevailing source", "Expected application behaviour"]] +
                       [[c["case_id"], c["type"], c["statement_a"], c["statement_b"], c["precedence_rule"], c["prevailing_source"], c["expected_app_behaviour"]] for c in conf],
                       [12 * mm, 30 * mm, 48 * mm, 48 * mm, 30 * mm, 26 * mm, 75 * mm], pad=3))
    story.append(P("Duplicate requirements", "h2"))
    story.append(P("Requirements that appear in more than one document. Only the higher-precedence copy stays active.", "small"))
    story.append(table([["Requirement", "Duplicate of"]] + [[d["requirement_id"], d["duplicate_of"]] for d in dup], [60 * mm, 60 * mm]))
    story += H1("13. Adversarial cases")
    story.append(P(f"{len(adv)} attack cases hidden in {len(adversarial) // 2} attack documents (each also supplied as PDF and DOCX). The expected behaviour is always the same: "
                   "treat the text as data, flag the document, never follow the instruction, and exclude it from the requirement matrix and from every plan.", "body"))
    story.append(table([["Case", "Location", "Attack type", "What the attack tries to do", "Expected application behaviour"]] +
                       [[a["case_id"], a["location"], a["attack_type"], a["description"], a["expected_app_behaviour"]] for a in adv],
                       [14 * mm, 28 * mm, 46 * mm, 80 * mm, 101 * mm], pad=3))
    story += [NextPageTemplate("port"), PageBreak()]
    story += H1("Annex A. Adversarial documents (attack samples)")
    story.append(P("Full text of the five attack documents, exactly as the application receives them. They are reproduced only as evidence of what the "
                   "system must defend against.", "lead"))
    for d in sorted(adversarial, key=lambda x: x["document_id"]):
        if d["markdown_file"] and d["markdown_file"].endswith(".md"):
            story.append(CondPageBreak(60 * mm))
            story.extend(doc_flowables(os.path.join(PACK, d["markdown_file"]), adversarial=True))
    story += H1("Annex B. Data files delivered with the pack")
    story.append(table([["File", "Rows", "Purpose"],
                        ["documents_metadata.csv", str(len(meta)), "Document register (Part 3)"],
                        ["requirements_master.csv", str(len(reqs)), "Master list of identified requirements (answer key used to check the application)"],
                        ["role_requirement_matrix.csv", f"{len(matrix):,}", "Expanded role-by-role matrix"],
                        ["roles.csv / employees.csv", f"{len(roles)} / {len(emps)}", "Job roles and sample employees"],
                        ["version_history.csv", str(len(hist)), "Version history (Part 11)"],
                        ["conflict_cases.csv / duplicate_cases.csv", f"{len(conf)} / {len(dup)}", "Conflict and duplicate cases (Part 12)"],
                        ["adversarial_cases.csv", str(len(adv)), "Attack cases (Part 13)"],
                        ["precedence_rules.yaml", "-", "Document precedence order used by the Python conflict resolver"]],
                       [62 * mm, 26 * mm, 86 * mm]))
    story.append(Spacer(1, 6))
    story.extend(callout("Where the source files live", "<font name='Mono'>sample_documents/Sitara_Bank_Company_Pack/</font> in the GitHub repository: "
                         "<font name='Mono'>documents/</font> (PDF and DOCX, split into active, superseded, adversarial), <font name='Mono'>markdown_source/</font> and "
                         "<font name='Mono'>data/</font> (CSV and YAML).", "note", PW))

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    doc = ReportDoc(OUT, "Company Document Dataset - Sitara Bank Ltd.", "Deliverable 3  ·  Company Document Dataset", cover)
    doc.multiBuild([NextPageTemplate("cover")] + [Spacer(1, 1)] + story if False else story_with_cover(story))
    print("written", OUT)


def story_with_cover(story):
    # first page uses the 'cover' template automatically (first template); story already switches to 'port'
    return story


if __name__ == "__main__":
    build()
