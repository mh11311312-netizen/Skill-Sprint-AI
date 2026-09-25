"""Step 10 - Role Requirement Matrix (the independent Python ground truth).
Rebuilt from the stored chunks whenever documents or roles change, so new roles and new documents
(including the hidden evaluation pack) are handled without code changes."""
import re
from config.loader import load_yaml
from src.text_utils import tokens
from src.audit import now
from role_matrix import extractor as ex
from contradiction_checks.source_conflicts import detect, precedence_level

DOC_REF = re.compile(r"\b([A-Z]{2,4}-(?:[A-Z]{2,4}-)?\d{2})\b")
PREREQ_RX = re.compile(r"^(?:the\s+)?(.+?) must be completed before (?:the |any )?(.+?)\.?$", re.I)
PREREQ_GENERIC = {"practical", "assessment", "training", "module"}


def role_names(db):
    return [r["name"] for r in db.roles.find().sort("role_id", 1)]


def rebuild_matrix(db, user="system"):
    names = role_names(db)
    untrusted = load_yaml("precedence_rules.yaml")["untrusted_categories"]
    docs = list(db.documents.find({"status": "Active"}))
    all_doc_ids = {d["document_id"] for d in db.documents.find({}, {"document_id": 1})}
    statements, reqs, unmapped_roles = [], [], set()

    for d in docs:
        if d.get("trust") == "Untrusted" or d["category"] in untrusted:
            continue
        for c in db.chunks.find({"document_id": d["document_id"], "version": d["version"]}):
            if c.get("quarantined"):
                continue
            text = ex.clean_text(c["text"])
            sid = f"{d['document_id']}-{c['section_id']}"
            ob = ex.obligation(text)
            roles, how, unmapped = ex.resolve_roles(c.get("applies_to_raw", ""), c["text"], names)
            statements.append({"id": sid, "document_id": d["document_id"], "category": d["category"],
                               "effective_date": d["effective_date"], "text": text, "section_id": c["section_id"],
                               "roles": roles, "all_roles": len(roles) == len(names), "obligation": ob})
            if ob == "Informational":
                continue
            unmapped_roles.update(unmapped)
            rtype = ex.requirement_type(text, ob)
            stage = ex.due_stage(text, d["category"])
            reqs.append({
                "requirement_id": sid, "document_id": d["document_id"], "document_title": d["title"],
                "version": d["version"], "category": d["category"], "section_id": c["section_id"],
                "section_heading": c.get("section_heading", ""), "chunk_id": c["chunk_id"], "page": c.get("page"),
                "text": text, "obligation": ob, "requirement_type": rtype, "roles": roles,
                "role_scope": "All Roles" if len(roles) == len(names) else "Role-Specific",
                "role_resolution": how, "competency": c.get("section_heading", ""),
                "priority": ex.priority(ob, d["document_id"], d["category"], stage), "due_stage": stage,
                "assessment": ex.assessment(rtype, ob), "precedence_level": precedence_level(d["category"]),
                "prerequisites": [], "overridden_by": None, "duplicate_of": None, "conflict_review": False,
                "active": True,
            })

    conflicts, duplicates = detect(statements)
    by_id = {r["requirement_id"]: r for r in reqs}
    for c in conflicts:
        if c["loser"] in by_id:
            by_id[c["loser"]]["overridden_by"] = c["winner"]
            by_id[c["loser"]]["active"] = False
        if c["status"] != "Resolved":
            for side in ("a", "b"):
                if c[side]["id"] in by_id:
                    by_id[c[side]["id"]]["conflict_review"] = True
    for dup in duplicates:
        if dup["duplicate"] in by_id and dup["keep"] in by_id and by_id[dup["keep"]]["active"]:
            by_id[dup["duplicate"]]["duplicate_of"] = dup["keep"]
            by_id[dup["duplicate"]]["active"] = False

    _link_prerequisites(reqs, statements)

    missing_refs = []
    for s in statements:
        for ref in set(DOC_REF.findall(s["text"])):
            if ref not in all_doc_ids:
                missing_refs.append({"statement": s["id"], "referenced": ref, "text": s["text"]})

    db.requirements.delete_many({})
    if reqs:
        db.requirements.insert_many(reqs)
    db.conflicts.delete_many({})
    records = [dict(c, kind="conflict") for c in conflicts]
    records += [dict(d, kind="duplicate") for d in duplicates]
    records += [dict(m, kind="missing_reference") for m in missing_refs]
    records += [{"kind": "unmapped_role", "name": n} for n in sorted(unmapped_roles)]
    if records:
        db.conflicts.insert_many(records)

    active = [r for r in reqs if r["active"]]
    summary = {"built_at": now(), "by": user, "requirements": len(reqs), "active": len(active),
               "mandatory": sum(r["obligation"] == "Mandatory" for r in active),
               "role_specific": sum(r["role_scope"] == "Role-Specific" for r in active),
               "conflicts": len(conflicts), "duplicates": len(duplicates),
               "missing_references": len(missing_refs), "roles": len(names)}
    db.matrix_builds.insert_one(summary)
    return summary


def _link_prerequisites(reqs, statements):
    rules = []
    for s in statements:
        m = PREREQ_RX.match(s["text"])
        if m:
            before = set(tokens(m.group(1), drop_filler=True)) - PREREQ_GENERIC
            after = set(tokens(m.group(2), drop_filler=True)) - PREREQ_GENERIC
            if before and after:
                rules.append((before, after, s["id"]))
    rule_ids = {rid for _, _, rid in rules}
    doable = [r for r in reqs if r["requirement_type"] in ("Must Complete", "Must Demonstrate")
              and r["active"] and r["requirement_id"] not in rule_ids]
    for before, after, rule_id in rules:
        toks = {r["requirement_id"]: set(tokens(r["text"], drop_filler=True)) for r in doable}
        pre = [r for r in doable if before <= toks[r["requirement_id"]] and not after <= toks[r["requirement_id"]]
               and not re.search(r"\bmust not\b|\buntil\b", r["text"], re.I)]
        for r in doable:
            if after <= toks[r["requirement_id"]] and not before <= toks[r["requirement_id"]]:
                for p in pre:
                    if p["requirement_id"] != r["requirement_id"] and set(p["roles"]) & set(r["roles"]):
                        if p["requirement_id"] not in r["prerequisites"]:
                            r["prerequisites"].append(p["requirement_id"])


def matrix_for_role(db, role, include_inactive=False):
    q = {"roles": role}
    if not include_inactive:
        q["active"] = True
    return list(db.requirements.find(q).sort([("due_stage", 1), ("document_id", 1)]))
