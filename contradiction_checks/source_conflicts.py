"""Steps 33/34 - Contradictions between SOURCE documents and precedence resolution.
Clauses from different documents are compared with TF-IDF weighted similarity (rare shared words such as
'USB' or 'password' count more than common ones such as 'branch' or 'approval').
  - same topic + same unit but different value (7 days vs 14 days)  -> Numeric conflict
  - same topic + opposite polarity (may use vs must not be used)    -> Polarity conflict
  - same meaning                                                    -> Duplicate
A general rule for all roles and a stricter rule for specific roles is NOT a conflict (scope rule).
The winner is chosen with config/precedence_rules.yaml."""
import math
import re
from collections import Counter
from config.loader import load_yaml
from src.text_utils import tokens

UNIT_RX = re.compile(
    r"(?P<cur>PKR\s*)?(?P<num>\d+(?::\d+)?(?:[.,]\d+)*)\s*(?P<unit>%|working days?|calendar days?|days?|hours?|"
    r"minutes?|years?|months?|weeks?|AM|PM|characters?|consecutive working days?)?", re.I)
PERMISSIVE = re.compile(r"\b(may|can|allowed|entitled|yes)\b", re.I)
RESTRICTIVE_EXTRA = re.compile(r"\bmust be approved\b|\bonly (after|with)\b|\brequires? [a-z ]*approval\b", re.I)
PREREQ_RULE = re.compile(r"must be completed before", re.I)
STRONG_NEGATIVE = re.compile(r"\b(must not|shall not|cannot|can not|not entitled|not permitted|prohibited|"
                             r"no longer|without|exempt|never)\b", re.I)


def unit_values(text):
    out = {}
    for m in UNIT_RX.finditer(text or ""):
        num = m.group("num").replace(",", "")
        if m.group("cur"):
            unit = "PKR"
        elif m.group("unit"):
            u = m.group("unit").lower()
            unit = "time" if u in ("am", "pm") else ("day" if "day" in u else u.rstrip("s"))
        else:
            continue                                   # bare numbers (section ids, counts) are ignored
        out.setdefault(unit, set()).add(num)
    return out


def precedence_level(category):
    return load_yaml("precedence_rules.yaml")["precedence_levels"].get(category, 9)


def resolve(a, b):
    la, lb = precedence_level(a["category"]), precedence_level(b["category"])
    if la != lb:
        w, l = (a, b) if la < lb else (b, a)
        return w, l, f"{w['category']} (level {min(la, lb)}) outranks {l['category']} (level {max(la, lb)})"
    if a["effective_date"] != b["effective_date"]:
        w, l = (a, b) if a["effective_date"] > b["effective_date"] else (b, a)
        return w, l, f"Same level: later effective date wins ({w['effective_date']} > {l['effective_date']})"
    return None, None, "Same precedence level and same effective date - cannot decide automatically"


class _Tfidf:
    def __init__(self, texts):
        self.docs = [Counter(tokens(t, drop_filler=True)) for t in texts]
        df = Counter(w for d in self.docs for w in d)
        n = len(self.docs)
        self.idf = {w: math.log((n + 1) / (c + 1)) + 1 for w, c in df.items()}
        self.vecs = []
        for d in self.docs:
            v = {w: tf * self.idf[w] for w, tf in d.items()}
            norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
            self.vecs.append({w: x / norm for w, x in v.items()})

    def sim(self, i, j):
        a, b = self.vecs[i], self.vecs[j]
        if len(a) > len(b):
            a, b = b, a
        return sum(x * b.get(w, 0.0) for w, x in a.items())


def detect(statements):
    """statements: dicts with id, document_id, category, effective_date, text, section_id, roles, obligation."""
    rules = load_yaml("validation_rules.yaml")
    tf = _Tfidf([s["text"] for s in statements])
    units = [unit_values(s["text"]) for s in statements]
    perm = [bool(PERMISSIVE.search(s["text"])) for s in statements]
    restr = [bool(STRONG_NEGATIVE.search(s["text"]) or RESTRICTIVE_EXTRA.search(s["text"])) for s in statements]
    ordering = [bool(PREREQ_RULE.search(s["text"])) for s in statements]
    conflicts, duplicates = [], []
    for i in range(len(statements)):
        a = statements[i]
        for j in range(i + 1, len(statements)):
            b = statements[j]
            if a["document_id"] == b["document_id"] or ordering[i] or ordering[j]:
                continue                               # sequencing rules are handled as prerequisites
            sim = tf.sim(i, j)
            if sim < min(rules["conflict_similarity"], rules["polarity_similarity"]):
                continue
            shared = set(units[i]) & set(units[j])
            numeric = sim >= rules["conflict_similarity"] and any(units[i][u] != units[j][u] for u in shared)
            # a permission in one source that the other source restricts
            polarity = sim >= rules["polarity_similarity"] and (
                (perm[i] and restr[j] and not perm[j]) or (perm[j] and restr[i] and not perm[i]))
            if numeric or polarity:
                ra, rb = set(a.get("roles", [])), set(b.get("roles", []))
                general_vs_specific = (a.get("all_roles") != b.get("all_roles")) and (ra < rb or rb < ra)
                if general_vs_specific:
                    conflicts.append({"type": "Scope-specific rule", "similarity": round(sim, 2), "a": _brief(a),
                                      "b": _brief(b), "winner": None, "loser": None, "status": "Both valid",
                                      "rule": "A general rule and a role-specific rule apply to different scopes."})
                    continue
                w, l, rule = resolve(a, b)
                conflicts.append({"type": "Numeric conflict" if numeric else "Polarity conflict",
                                  "similarity": round(sim, 2), "a": _brief(a), "b": _brief(b),
                                  "winner": w["id"] if w else None, "loser": l["id"] if l else None,
                                  "rule": rule, "status": "Resolved" if w else "Manual Review Required"})
            elif sim >= rules["conflict_similarity"] and sim >= rules["source_duplicate_similarity"] and a.get("obligation") == b.get("obligation"):
                w, l, _ = resolve(a, b)
                keep, drop = (w, l) if w else (a, b)
                duplicates.append({"keep": keep["id"], "duplicate": drop["id"], "similarity": round(sim, 2)})
    return conflicts, duplicates


def _brief(s):
    return {"id": s["id"], "document_id": s["document_id"], "section_id": s["section_id"],
            "category": s["category"], "effective_date": s["effective_date"], "text": s["text"]}
