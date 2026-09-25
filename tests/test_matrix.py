"""Role Requirement Matrix, source conflicts, precedence and duplicates."""


def test_matrix_meets_dataset_minimums(ctx):
    active = ctx.requirements.count_documents({"active": True})
    mandatory = ctx.requirements.count_documents({"active": True, "obligation": "Mandatory"})
    specific = ctx.requirements.count_documents({"active": True, "role_scope": "Role-Specific"})
    assert active >= 150 and mandatory >= 50 and specific >= 30


def test_faq_conflict_resolved_by_policy(ctx):
    r = ctx.requirements.find_one({"requirement_id": "FAQ-02-1.1"})
    assert r["active"] is False and r["overridden_by"] == "POL-04-3.2"


def test_compliance_conflict_uses_precedence(ctx):
    c = ctx.conflicts.find_one({"kind": "conflict", "loser": "CMP-01-3.1"})
    assert c and c["winner"] == "POL-07-2.1" and "outranks" in c["rule"]


def test_scope_specific_rule_is_not_a_conflict(ctx):
    c = ctx.conflicts.find_one({"kind": "conflict", "type": "Scope-specific rule"})
    assert c is not None
    assert ctx.requirements.find_one({"requirement_id": "CMP-01-2.5"})["active"] is True


def test_role_specific_requirements(ctx):
    r = ctx.requirements.find_one({"requirement_id": "POL-07-5.1"})
    assert "Cash Teller" in r["roles"] and r["role_scope"] == "Role-Specific"


def test_duplicates_detected(ctx):
    assert ctx.conflicts.find_one({"kind": "duplicate", "duplicate": "CMP-01-2.1", "keep": "POL-04-2.1"})


def test_missing_reference_detected(ctx):
    assert ctx.conflicts.find_one({"kind": "missing_reference", "referenced": "MKT-GD-01"})


def test_prerequisite_linked(ctx):
    r = ctx.requirements.find_one({"requirement_id": "POL-06-2.2"})
    assert "POL-04-2.1" in r["prerequisites"]
