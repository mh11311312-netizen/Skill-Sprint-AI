"""Steps 44/45 - GenAI consistency: compare two generations of the same task on structured fields only."""


def _jaccard(a, b):
    a, b = set(a), set(b)
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def structured_view(plan_json):
    mods = plan_json.get("modules", [])
    return {
        "mandatory_requirements": {rc["requirement_id"] for m in mods for rc in m.get("requirements_covered", []) if rc.get("mandatory")},
        "sources": {rc["source_document_id"] for m in mods for rc in m.get("requirements_covered", [])},
        "module_categories": {m.get("category") for m in mods},
        "assessment_topics": {(m.get("assessment") or {}).get("topic", "").lower().strip() for m in mods} - {""},
        "stages": {(rc["requirement_id"], rc.get("due_stage")) for m in mods for rc in m.get("requirements_covered", [])},
    }


def compare_generations(p1, p2):
    a, b = structured_view(p1), structured_view(p2)
    scores = {k: round(_jaccard(a[k], b[k]) * 100, 1) for k in ("mandatory_requirements", "sources", "module_categories", "stages")}
    # assessment topics are free text, so they are compared loosely
    from src.text_utils import cosine
    scores["assessment_topics"] = round(cosine(" ".join(a["assessment_topics"]), " ".join(b["assessment_topics"])) * 100, 1)
    overall = round(sum(scores.values()) / len(scores), 1)
    differences = {
        "only_in_run_1": sorted(a["mandatory_requirements"] - b["mandatory_requirements"]),
        "only_in_run_2": sorted(b["mandatory_requirements"] - a["mandatory_requirements"]),
        "sources_only_in_run_1": sorted(a["sources"] - b["sources"]),
        "sources_only_in_run_2": sorted(b["sources"] - a["sources"]),
    }
    major = scores["mandatory_requirements"] < 90 or scores["sources"] < 90
    return {"scores": scores, "consistency_score": overall, "differences": differences, "major_difference": major}
