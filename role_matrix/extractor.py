"""Step 11 - Requirement extraction (deterministic Python rules, no AI).
Turns each source clause into a requirement record: obligation, type, roles, stage, priority, assessment."""
import re
from config.loader import load_yaml

STAGE_ORDER = None


def stages():
    return [s["name"] for s in load_yaml("stages.yaml")["stages"]]


def stage_index(name):
    names = stages()
    return names.index(name) if name in names else len(names)


def obligation(text):
    rules = load_yaml("requirement_rules.yaml")["obligation_patterns"]
    for label in ("Mandatory", "Recommended", "Optional"):
        flags = re.I if label != "Optional" else 0          # 'May' as a month is not an obligation
        if re.search(rules[label], text, flags):
            return label
    return "Informational"


def requirement_type(text, ob):
    if ob != "Mandatory":
        return ob
    for label, rx in load_yaml("requirement_rules.yaml")["type_patterns"].items():
        if re.search(rx, text, re.I):
            return label
    return "Must Know"


def due_stage(text, category):
    if re.search(r"\bDay 1\b|\bfirst day of joining\b", text):
        return "Day 1"
    if re.search(r"first week of joining", text, re.I):
        return "Week 1"
    m = re.search(r"within (\d+) days of joining", text, re.I)
    if m:
        n = int(m.group(1))
        for st in load_yaml("stages.yaml")["stages"]:
            if n <= st["due_day"] and st["name"] != "Day 1":
                return st["name"]
        return stages()[-1]
    if re.search(r"end of probation", text, re.I):
        return "First 90 Days"
    return load_yaml("stages.yaml")["default_stage_by_category"].get(category, "Week 2")


def priority(ob, document_id, category, stage):
    if ob != "Mandatory":
        return "Low"
    high_docs = load_yaml("validation_rules.yaml")["high_priority_documents"]
    if document_id in high_docs or category == "Compliance" or stage == "Day 1":
        return "High"
    return "Medium"


def assessment(rtype, ob):
    if ob != "Mandatory":
        return "None"
    return {"Must Demonstrate": "Practical Assessment",
            "Must Acknowledge": "Signed Acknowledgement"}.get(rtype, "Knowledge Quiz")


def _match_role(name, role_names):
    n = name.strip().lower().rstrip(".")
    for r in role_names:
        rl = r.lower()
        if n in (rl, rl + "s", rl + "es"):
            return r
    return None


def resolve_roles(applies_raw, clause_text, role_names):
    """Returns (roles, how_resolved, unmapped_names)."""
    m = re.search(r"\(Applies to:\s*([^)]+)\)", clause_text)
    raw = m.group(1) if m else (applies_raw or "")
    phrases = load_yaml("requirement_rules.yaml")["all_roles_phrases"]
    if raw and raw.strip().lower() in phrases:
        return list(role_names), "applies_line", []
    if raw:
        parts = [p for p in re.split(r",|\band\b", raw) if p.strip()]
        found, unmapped = [], []
        for p in parts:
            r = _match_role(p, role_names)
            (found.append(r) if r else unmapped.append(p.strip()))
        if found:
            return sorted(set(found), key=role_names.index), "applies_line", unmapped
        return list(role_names), "unmapped_applies_line", unmapped
    # No 'Applies to' information (unseen document format): look for role names in the text
    mentioned = [r for r in role_names if re.search(rf"\b{re.escape(r)}s?\b", clause_text, re.I)]
    if mentioned:
        return mentioned, "inferred_from_text", []
    return list(role_names), "inferred_all", []


def clean_text(text):
    return re.sub(r"\s*\(Applies to:\s*[^)]+\)", "", text).strip()
