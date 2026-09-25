"""A local stand-in for the Gemini API used ONLY by automated tests (no network, no API cost).
It reads the source clauses in the prompt and builds a plan the way a well-behaved model would,
optionally injecting realistic mistakes so the Python validator can be tested against them.
The real application always calls the real API (genai_pipeline/client.py)."""
import json
import re

LINE = re.compile(r"^\[(?P<doc>[A-Z0-9-]+) §(?P<sec>[\d.]+)\] \((?P<head>[^)]*)\) (?P<text>.+)$", re.M)


def _stage(text, category):
    if "Day 1" in text:
        return "Day 1"
    if "first week" in text:
        return "Week 1"
    m = re.search(r"within (\d+) days of joining", text)
    if m:
        n = int(m.group(1))
        return "Week 1" if n <= 7 else "Week 2" if n <= 14 else "First 30 Days" if n <= 30 else "First 60 Days" if n <= 60 else "First 90 Days"
    if "end of probation" in text:
        return "First 90 Days"
    return {"Policy": "Week 1", "Handbook": "Week 1", "Compliance": "First 30 Days", "SOP": "Week 2",
            "Role Description": "Week 2", "Process Manual": "First 30 Days", "FAQ": "Week 2"}.get(category, "Week 2")


class FakeLLM:
    model = "fake-test-model"

    def __init__(self, mistakes=(), fail_first=0):
        self.mistakes, self.fail_first, self.calls = set(mistakes), fail_first, 0

    def generate(self, system, prompt, temperature):
        self.calls += 1
        if self.calls <= self.fail_first:
            return "Sorry, here is your plan: {not json"
        role = re.search(r"- Role: (.+)", prompt)
        emp = re.search(r"- Employee ID: (.+)", prompt)
        cats = dict(re.findall(r'<source_document id="([^"]+)"[^>]*category="([^"]+)"', prompt))
        if "Requested topic:" in prompt:
            items = [m for m in LINE.finditer(prompt)]
            doc = items[0]["doc"]
            return json.dumps(self._module("TOPIC-1", doc, [m for m in items if m["doc"] == doc], cats.get(doc, "Policy")))
        if "CURRENT MODULE" in prompt:
            return json.dumps(self._module_from(prompt, cats, "M-REGEN"))
        modules, skip = [], {"FAQ"}
        by_doc = {}
        for m in LINE.finditer(prompt):
            if cats.get(m["doc"]) in skip or not re.search(r"\b(must|shall|required)\b", m["text"], re.I):
                continue
            by_doc.setdefault(m["doc"], []).append(m)
        for i, (doc, items) in enumerate(by_doc.items(), start=1):
            modules.append(self._module(f"M{i:02d}", doc, items, cats[doc]))
        plan = {"role": role.group(1).strip() if role else "?", "employee_id": emp.group(1).strip() if emp else "?",
                "summary": "Plan built from approved sources.", "modules": modules, "insufficient_information": []}
        self._inject(plan)
        return "```json\n" + json.dumps(plan) + "\n```"

    def _module(self, mid, doc, items, cat):
        rcs = [{"requirement_id": f"{doc}-{x['sec']}", "statement": x["text"], "mandatory": True,
                "due_stage": _stage(x["text"], cat), "source_document_id": doc, "source_section_id": x["sec"]} for x in items]
        stage = min((r["due_stage"] for r in rcs), key=["Day 1", "Week 1", "Week 2", "First 30 Days", "First 60 Days", "First 90 Days"].index)
        first = items[0]
        return {"module_id": mid, "module_title": f"{first['head']} ({doc})", "category": "Compliance" if cat == "Compliance" else "Policy",
                "purpose": f"Understand and apply {first['head']}.", "stage": stage, "mandatory": True, "priority": "High",
                "difficulty": "Beginner", "estimated_duration_minutes": 45, "prerequisites": [],
                "learning_objectives": [f"Apply the rules in {doc}."], "key_concepts": [first["head"]],
                "learning_activities": ["Read the source sections"], "completion_criteria": "Pass the quiz with 70%.",
                "requirements_covered": rcs,
                "checklist": [{"activity": first["text"][:120], "required": True, "due_stage": stage, "responsible": "Employee",
                               "source_document_id": doc, "source_section_id": first["sec"]}],
                "tasks": [{"task_id": f"{mid}-T1", "description": f"Practise: {first['text']}", "expected_outcome": "Rule applied correctly.",
                           "completion_criteria": "Checked by manager.", "difficulty": "Beginner", "due_stage": stage, "scenario_based": True,
                           "source_document_id": doc, "source_section_id": first["sec"]}],
                "quiz": [{"question_id": f"{mid}-Q1", "type": "true_false", "question": f"True or false: {first['text']}",
                          "options": ["True", "False"], "correct_answers": ["True"], "explanation": "Stated in the source.",
                          "difficulty": "Beginner", "source_document_id": doc, "source_section_id": first["sec"]}],
                "assessment": {"type": "knowledge", "topic": first["head"], "rubric": []}}

    def _module_from(self, prompt, cats, mid):
        cur = json.loads(prompt.split("CURRENT MODULE", 1)[1].split("\n", 1)[1].split("\n\n  Rewrite", 1)[0].split("\n\nRewrite", 1)[0])
        doc = cur["requirements_covered"][0]["source_document_id"]
        items = [m for m in LINE.finditer(prompt) if m["doc"] == doc and re.search(r"\b(must|shall|required)\b", m["text"], re.I)]
        new = self._module(cur["module_id"], doc, items, cats.get(doc, "Policy"))
        return new

    def _inject(self, plan):
        mods = plan["modules"]
        if "hallucination" in self.mistakes:
            mods[0]["requirements_covered"].append({"requirement_id": "POL-04-9.9", "statement": "Employees must learn cryptocurrency trading.",
                                                     "mandatory": True, "due_stage": "Week 1", "source_document_id": "POL-04", "source_section_id": "9.9"})
        if "wrong_number" in self.mistakes:
            for m in mods:
                for rc in m["requirements_covered"]:
                    if rc["requirement_id"] == "POL-04-3.2":
                        rc["statement"] = "Employees must change their passwords every 90 days."
        if "missing" in self.mistakes:
            mods[0]["requirements_covered"] = mods[0]["requirements_covered"][:1]
        if "outdated" in self.mistakes:
            mods[0]["requirements_covered"].append({"requirement_id": "POL-03-9.1", "statement": "Old leave rule.", "mandatory": True,
                                                     "due_stage": "Week 1", "source_document_id": "ADV-03", "source_section_id": "1.1"})
        if "bad_quiz" in self.mistakes:
            mods[0]["quiz"][0]["correct_answers"] = ["Maybe"]
        if "sequence" in self.mistakes and len(mods) > 1:
            mods[1]["prerequisites"] = [mods[0]["module_id"]]
            mods[0]["stage"], mods[1]["stage"] = "First 90 Days", "Day 1"
