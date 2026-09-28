"""Deliverable 4 - GenAI Pipeline Evidence (PDF).
Runs the real Pipeline 1 code (capture_genai.py), then lays the evidence out as a submission-ready PDF.
    python -m src.evidence.build_genai_evidence            # offline stand-in model (no API key, no cost)
    python -m src.evidence.build_genai_evidence --live     # the real API configured in .env (recommended for final submission)
    python -m src.evidence.build_genai_evidence --rebuild  # only re-draw the PDF from the last capture"""
import json
import os
import re
import subprocess
import sys

from reportlab.graphics.shapes import Drawing, Rect, String, Line, Polygon, PolyLine
from reportlab.lib.units import mm
from reportlab.platypus import NextPageTemplate, PageBreak, Spacer, CondPageBreak, KeepTogether

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from src.evidence.pdfkit import *   # noqa: E402,F401,F403
from src.evidence import capture_genai   # noqa: E402

OUT = os.path.join(ROOT, "reports", "Deliverable_4_GenAI_Pipeline_Evidence.pdf")
BUNDLE = os.path.join(ROOT, "documentation", "evidence", "genai_capture.json")
PW = 174 * mm


def env_example():
    vals = {}
    for ln in open(os.path.join(ROOT, ".env.example"), encoding="utf-8"):
        if "=" in ln and not ln.lstrip().startswith("#"):
            k, v = ln.strip().split("=", 1)
            vals[k] = v
    return vals


def extract_json(text):
    a, b = text.find("{"), text.rfind("}")
    return json.loads(text[a:b + 1])


def pretty(text):
    return json.dumps(extract_json(text), indent=2, ensure_ascii=False)


def typ(p, defs):
    if "$ref" in p:
        return p["$ref"].split("/")[-1]
    if "anyOf" in p:
        return " or ".join(typ(x, defs) for x in p["anyOf"] if x.get("type") != "null") + " (optional)"
    if "enum" in p:
        return "one of: " + ", ".join(f"'{e}'" for e in p["enum"])
    t = p.get("type", "?")
    if t == "array":
        return f"list of {typ(p.get('items', {}), defs)}"
    return t


def constraint(p, name=""):
    bits = []
    for k, label in (("minLength", "min length"), ("minItems", "at least"), ("minimum", "min"), ("maximum", "max"), ("pattern", "pattern")):
        if k in p:
            bits.append(f"{label} {p[k]}" + (" item(s)" if k == "minItems" else ""))
    return "; ".join(bits) or "-"


def schema_rows(schema, model):
    d = schema["$defs"] if model != "OnboardingPlan" else schema
    node = schema if model == "OnboardingPlan" else schema["$defs"][model]
    req = set(node.get("required", []))
    return [[f"<font name='Mono' size='7.4'>{n}</font>", typ(p, schema.get("$defs", {})), "Yes" if n in req else "No", constraint(p)]
            for n, p in node["properties"].items()]


def flow_diagram(retry_label):
    w, h = 493, 178
    d = Drawing(w, h)
    def box(x, y, bw, bh, t1, t2, fill, stroke, tc=INK):
        d.add(Rect(x, y, bw, bh, rx=6, ry=6, fillColor=fill, strokeColor=stroke, strokeWidth=1))
        d.add(String(x + bw / 2, y + bh - 17, t1, fontName="Sans-B", fontSize=8.6, fillColor=tc, textAnchor="middle"))
        for i, ln in enumerate(t2.split("|")):
            d.add(String(x + bw / 2, y + bh - 30 - i * 10, ln, fontName="Sans", fontSize=7.2, fillColor=MUTED, textAnchor="middle"))
    def arrow(x1, y1, x2, y2, col=ESP):
        d.add(Line(x1, y1, x2, y2, strokeColor=col, strokeWidth=1.4))
        d.add(Polygon([x2, y2, x2 - 5, y2 + 3, x2 - 5, y2 - 3] if x2 > x1 else [x2, y2, x2 + 5, y2 + 3, x2 + 5, y2 - 3], fillColor=col, strokeColor=col))
    bw, bh, gap, y = 82, 58, 20.5, 100
    xs = [i * (bw + gap) for i in range(5)]
    box(xs[0], y, bw, bh, "Approved clauses", "role-filtered|Active + Trusted only", CREAM, ESP)
    box(xs[1], y, bw, bh, "Prompt template", "v1.2 + employee profile|+ coverage checklist", CREAM, ESP)
    box(xs[2], y, bw, bh, "GenAI API", "JSON mode|system + user prompt", AMBER_L, GOLD)
    box(xs[3], y, bw, bh, "Schema check", "Pydantic: types, enums,|required fields, patterns", GREEN_L, GREEN)
    box(xs[4], y, bw, bh, "Merge + validate", "modules merged into|one plan; Pipeline 2", GREEN_L, GREEN)
    for i in range(4):
        arrow(xs[i] + bw, y + bh / 2, xs[i + 1], y + bh / 2)
    d.add(String(xs[3] + bw + gap / 2, y + bh / 2 + 6, "valid", fontName="Sans-B", fontSize=6.6, fillColor=GREEN, textAnchor="middle"))
    # retry loop under boxes 3 <- 4
    x4, x3 = xs[3] + bw / 2, xs[2] + bw / 2
    d.add(PolyLine([x4, y, x4, 62, x3, 62, x3, y - 3], strokeColor=RED, strokeWidth=1.4))
    d.add(Polygon([x3, y - 1, x3 - 3, y - 7, x3 + 3, y - 7], fillColor=RED, strokeColor=RED))
    d.add(String((x3 + x4) / 2, 49, "invalid  ->  retry with the validator's error appended", fontName="Sans-B", fontSize=7.2, fillColor=RED, textAnchor="middle"))
    d.add(String((x3 + x4) / 2, 38, retry_label, fontName="Sans", fontSize=7, fillColor=MUTED, textAnchor="middle"))
    d.add(Rect(0, 0, 3, 3, fillColor=None, strokeColor=None))
    d.add(String(0, 20, "Only genai_pipeline/client.py contacts the external API. Every attempt, success or failure, is written to the generation log.",
                 fontName="Sans-I", fontSize=7.2, fillColor=MUTED))
    d.add(String(0, 8, "Business rules, schema validation, precedence, escalation and audit stay in Python (SRS 1.8, item 18).",
                 fontName="Sans-I", fontSize=7.2, fillColor=MUTED))
    return d


def build(bundle):
    live = bundle["live"]
    n, rt, ex, bg = (bundle["scenarios"][k] for k in ("normal", "retry", "exhausted", "budget"))
    cfg, ee = bundle["config"], env_example()
    model_cfg = ee.get("OPENAI_MODEL", cfg["OPENAI_MODEL"])
    captured_model = bundle["model_used"]
    sample = n["sample"]
    tpl = bundle["templates"]

    def cover(c, doc):
        draw_cover(c, doc, "", ["GenAI Pipeline", "Evidence"],
                   "How Pipeline 1 talks to the Generative AI API: the model, the versioned prompts, the exact requests and responses, "
                   "the structured JSON output, the failures we provoked on purpose, and the retries that recovered from them.",
                   [("Deliverable", "4 of 18  -  GenAI Pipeline Evidence (SRS 1.10)"), ("Pipeline", "Pipeline 1  -  Python + Generative AI API"),
                    ("Model configured", f"{model_cfg}  (OpenAI, JSON mode)"),
                    ("Evidence captured with", (f"Live API run  -  {captured_model}" if live else "Offline stand-in model  -  see note on page 3")),
                    ("Captured on", bundle["captured_at"])], "Deliverable 4")

    story = [NextPageTemplate("port"), PageBreak(), P("Contents", "h1"), GoldRule(), Spacer(1, 6), make_toc(), PageBreak()]

    # ------------------------------------------------------------------ 1
    story += H1("1. Evidence at a glance")
    story.append(P("SRS Section 1.10, item 4 asks for ten things. Each one is shown below with a pointer to the section that contains it. "
                   "The evidence was produced by running the real Pipeline 1 code (<font name='Mono'>genai_pipeline/</font>) against the real "
                   "Sitara Bank document set for employee EMP-002 (Customer Service Officer) - it is not written by hand.", "body"))
    if live:
        story += callout("Capture source: live API", f"Every request in this document was sent to <b>{esc(captured_model)}</b> on {esc(bundle['captured_at'])}. "
                         "Only the failure demonstrations are induced faults (see section 10), because a healthy API does not fail on demand.", "ok", PW)
    else:
        story += callout("Capture note - please read",
                         "This machine has no API key, so the model calls in this capture were answered by <b>fake-test-model</b>, the project's offline "
                         "stand-in (<font name='Mono'>tests/fake_llm.py</font>). Everything around the model is the real, unmodified production code: "
                         "template loading, clause retrieval, batching, request building, JSON extraction, Pydantic validation, retry logic, logging, "
                         "and the time budget. Because the stand-in answers instantly, per-call timings read 0.0 s. "
                         "<b>For the final submission, re-run <font name='Mono'>python -m src.evidence.build_genai_evidence --live</font> with your "
                         "OPENAI_API_KEY set: this same PDF is regenerated with the real model name, real prompts and real latency.</b>", "warn", PW)
    story.append(stat_cards([(n["calls"], "API requests in one plan"), (n["modules"], "modules generated"), (rt["attempts"], "attempts to recover"),
                             (4, "failure types shown"), (3, "prompt templates")]))
    story.append(Spacer(1, 10))
    story.append(table([["SRS item", "Where", "What you will find"],
                        ["GenAI API used", "Section 2", "Provider, SDK call, JSON mode, alternative provider, data-flow diagram"],
                        ["Model used", "Section 3", "Configured model, reasoning effort, temperature policy, model recorded per request"],
                        ["Prompt templates", "Section 4", "All three templates, with the full system and user prompt of the main one"],
                        ["Prompt versions", "Section 5", "Change log of every template and how the version is stored with each plan"],
                        ["Generation configuration", "Section 6", "Every setting, its value, its meaning, and the effective API request"],
                        ["Sample requests", "Section 7", "A real request exactly as sent"],
                        ["Sample responses", "Section 8", "The raw response received for that request"],
                        ["Structured JSON output", "Section 9", "The schema, a validated module, and Pipeline 2's verdict on the whole plan"],
                        ["Failure examples", "Section 10", "Non-JSON reply, schema-invalid JSON, exhausted retries, and a time-budget miss"],
                        ["Retry evidence", "Section 11", "Attempt-by-attempt log, the feedback appended to the prompt, and the retry rules"]],
                       [40 * mm, 24 * mm, 110 * mm]))

    # ------------------------------------------------------------------ 2
    story += [PageBreak()] + H1("2. GenAI API used")
    story.append(P("Pipeline 1 uses a hosted Generative AI API to <i>write</i> onboarding content. It never decides whether that content is correct - "
                   "that is Pipeline 2's job, in plain Python.", "lead"))
    story.append(kv([("Provider (default)", "OpenAI - Chat Completions API"), ("How it is called", "<font name='Mono'>openai</font> Python SDK, "
                     "<font name='Mono'>client.chat.completions.create(...)</font> with a system message and a user message"),
                     ("Output mode", "<font name='Mono'>response_format = {\"type\": \"json_object\"}</font> - the API is told to return exactly one JSON object"),
                     ("Alternative provider", "Google Gemini - <font name='Mono'>models.generate_content</font> with <font name='Mono'>response_mime_type = application/json</font>. "
                      "Switch with <font name='Mono'>GENAI_PROVIDER</font> in .env; no code change"),
                     ("Where in the code", "<font name='Mono'>genai_pipeline/client.py</font> is the only file that contacts the external API"),
                     ("Credentials", "API key only in .env (never committed) and as an environment variable on the deployment platform"),
                     ("SDK retries", "Disabled (<font name='Mono'>max_retries=0</font>) - the project's own retry logic is used so every attempt is logged")]))
    story.append(P("Data flow", "h2"))
    story.append(flow_diagram(f"up to {cfg['GENAI_MAX_RETRIES']} attempts per request; back-off of 2 s, 4 s, 8 s (never past the time budget)"))
    story.append(P("What the API may and may not do", "h2"))
    story += bullets(["<b>May:</b> read approved clauses and write modules, checklists, tasks, quiz questions and rubrics as structured JSON.",
                      "<b>May not:</b> replace Python business rules, ground-truth validation, schema validation, policy precedence, escalation or audit logic (SRS 1.8, item 18).",
                      "<b>Untrusted input:</b> document text is wrapped in <font name='Mono'>&lt;source_document&gt;</font> tags and the system prompt states that "
                      "anything inside is data, never an instruction (see the SECURITY RULES in section 4)."])

    # ------------------------------------------------------------------ 3
    story += H1("3. Model used")
    story.append(table([["Item", "Configured for the application (.env.example)", "Used in this capture"],
                        ["Provider", ee.get("GENAI_PROVIDER", "openai"), cfg["GENAI_PROVIDER"] if live else "offline stand-in"],
                        ["Model", model_cfg, captured_model],
                        ["Reasoning effort", ee.get("GENAI_REASONING_EFFORT", "-") + "  (GPT-5 family: less internal thinking, fewer tokens)", cfg["GENAI_REASONING_EFFORT"] or "not applicable"],
                        ["Temperature", ee.get("GENAI_TEMPERATURE", "0.2") + "  (sent only to models that accept it; GPT-5 models use their fixed default)", str(cfg["GENAI_TEMPERATURE"])],
                        ["Alternative model", "gemini-2.5-flash (GENAI_PROVIDER=gemini)", "-"]],
                       [34 * mm, 90 * mm, 50 * mm]))
    story.append(Spacer(1, 6))
    story.append(P("The model name is stored with every request (<font name='Mono'>generation_logs.model</font>) and with every plan "
                   "(<font name='Mono'>plan.generation.model</font>), so any plan can be traced back to the exact model that wrote it. "
                   "It is shown in the plan header of the application and in the <b>Generation log</b> tab.", "body"))

    # ------------------------------------------------------------------ 4
    story += [PageBreak()] + H1("4. Prompt templates")
    story.append(P("Prompts are never scattered through the source code. They live in one folder, "
                   "<font name='Mono'>prompt_templates/</font>, as versioned YAML files loaded by "
                   "<font name='Mono'>genai_pipeline/generator.py::load_template</font>.", "body"))
    story.append(table([["Template", "Version", "Used for", "Placeholders filled at run time"],
                        ["onboarding_plan", tpl["onboarding_plan"]["version"], "Generate part of a role's plan from a batch of approved clauses",
                         "company, employee profile, stages, min/max modules, source clauses, coverage checklist"],
                        ["module_regeneration", tpl["module_regeneration"]["version"], "Rewrite one module after a policy update, or add modules for missing requirements",
                         "company, role, level, stages, reason, current module, source clauses"],
                        ["topic_module", tpl["topic_module"]["version"], "Answer a free-text topic request only if the approved sources cover it (hallucination challenge)",
                         "company, requested topic, matching clauses"]],
                       [36 * mm, 15 * mm, 68 * mm, 55 * mm]))
    story.append(P("System prompt - onboarding_plan", "h2"))
    story.append(P("Sent as the <b>system</b> message. The SECURITY RULES are what stop a document from hijacking the model.", "small"))
    story += code(tpl["onboarding_plan"]["system"], label="prompt_templates/onboarding_plan.yaml  ·  system")
    story.append(P("User prompt template - onboarding_plan", "h2"))
    story.append(P("Sent as the <b>user</b> message. Curly-brace fields are filled in per employee and per batch of clauses.", "small"))
    story += code(tpl["onboarding_plan"]["user"], label="prompt_templates/onboarding_plan.yaml  ·  user")
    story.append(P("System prompt - module_regeneration", "h2"))
    story += code(tpl["module_regeneration"]["system"], label="prompt_templates/module_regeneration.yaml  ·  system")
    story.append(P("System prompt - topic_module", "h2"))
    story += code(tpl["topic_module"]["system"], label="prompt_templates/topic_module.yaml  ·  system")

    # ------------------------------------------------------------------ 5
    story += H1("5. Prompt versions")
    story.append(P("Every template carries a version and a change log. Changing a prompt means bumping the version, so a plan can always be "
                   "explained by the exact wording that produced it.", "body"))
    for name in ("onboarding_plan", "module_regeneration", "topic_module"):
        t = tpl[name]
        story.append(P(f"{name}  -  current version {t['version']}", "h3"))
        rows = [["Version", "Change"]]
        for line in t.get("changelog", []):
            v, _, txt = str(line).partition(": ")
            rows.append([v, txt])
        story.append(table(rows, [22 * mm, 152 * mm]))
    story.append(P("How the version is stored with each plan", "h2"))
    gm = n["gen_meta"]
    keep = {k: gm[k] for k in ("model", "provider", "prompt_template", "prompt_version", "temperature", "attempts", "batches", "generated_at", "seconds") if k in gm}
    story += code(json.dumps(keep, indent=2, default=str), label=f"plan.generation  ·  plan {n['plan_id']}")

    # ------------------------------------------------------------------ 6
    story += [PageBreak()] + H1("6. Generation configuration")
    story.append(P("All behaviour below is set in <font name='Mono'>.env</font> - no code change is needed to tune it.", "body"))
    def cv(k, d="-"):
        v = cfg.get(k)
        return str(v if v not in (None, "") else d)
    story.append(table([["Setting", "Configured (.env.example)", "This capture", "Meaning"],
                        ["GENAI_PROVIDER", ee.get("GENAI_PROVIDER", "-"), cv("GENAI_PROVIDER"), "Which API client is used"],
                        ["OPENAI_MODEL", model_cfg, captured_model, "Model name sent with every request"],
                        ["GENAI_REASONING_EFFORT", ee.get("GENAI_REASONING_EFFORT", "-"), cv("GENAI_REASONING_EFFORT", "n/a"), "GPT-5 family: how much the model thinks before answering"],
                        ["GENAI_TEMPERATURE", ee.get("GENAI_TEMPERATURE", "-"), cv("GENAI_TEMPERATURE"), "Randomness (models that allow it)"],
                        ["GENAI_MAX_RETRIES", ee.get("GENAI_MAX_RETRIES", "-"), cv("GENAI_MAX_RETRIES"), "Attempts per request before giving up"],
                        ["GENAI_TIMEOUT_SECONDS", ee.get("GENAI_TIMEOUT_SECONDS", "-"), cv("GENAI_TIMEOUT_SECONDS"), "Longest a single API call may take"],
                        ["GENAI_BATCH_CLAUSES", ee.get("GENAI_BATCH_CLAUSES", "-"), cv("GENAI_BATCH_CLAUSES"), "Source clauses per request (small = fast, reliable)"],
                        ["GENAI_PARALLEL", ee.get("GENAI_PARALLEL", "-"), cv("GENAI_PARALLEL"), "Requests sent at the same time"],
                        ["GENAI_COVERAGE_ROUNDS", ee.get("GENAI_COVERAGE_ROUNDS", "-"), cv("GENAI_COVERAGE_ROUNDS"), "Extra gap-fill passes for clauses the model skipped"],
                        ["GENAI_TIME_BUDGET", ee.get("GENAI_TIME_BUDGET", "-"), cv("GENAI_TIME_BUDGET"), "Seconds allowed for a whole plan (SRS: 30 s)"],
                        ["GENAI_REGEN_TIME_BUDGET", ee.get("GENAI_REGEN_TIME_BUDGET", "-"), cv("GENAI_REGEN_TIME_BUDGET"), "Seconds allowed for 'Regenerate selected modules'"]],
                       [46 * mm, 30 * mm, 26 * mm, 72 * mm], col_style={0: "cellm"}))
    story.append(P("Effective API request", "h2"))
    story.append(P("What the client actually sends for one request (message bodies shortened to their length here; the full text is in section 7).", "small"))
    eff = {"model": model_cfg, "messages": [{"role": "system", "content": f"<{len(sample['system']):,} characters - section 4>"},
                                              {"role": "user", "content": f"<{len(sample['prompt']):,} characters - section 7>"}],
           "response_format": {"type": "json_object"}}
    if ee.get("GENAI_REASONING_EFFORT"):
        eff["reasoning_effort"] = ee["GENAI_REASONING_EFFORT"]
    story += code(json.dumps(eff, indent=2), label="openai chat.completions.create(**args)  ·  GPT-5 family")

    # ------------------------------------------------------------------ 7
    story += [PageBreak()] + H1("7. Sample request")
    story.append(P(f"One real request from the capture run: <b>{esc(sample['purpose'])}</b> for employee EMP-002. "
                   "A role can have 80+ mandatory clauses, so the sources are split into small batches and each batch is its own request.", "body"))
    story.append(kv([("Purpose", sample["purpose"]), ("Model", sample["model"]), ("System message", f"{len(sample['system']):,} characters (section 4)"),
                     ("User message", f"{len(sample['prompt']):,} characters (below)"), ("Temperature / mode", f"{cfg['GENAI_TEMPERATURE']}  /  JSON object")]))
    story += code(sample["prompt"], label="user message exactly as sent", width_chars=108, size=7.1)
    story += callout("What to notice", "The <b>source clauses</b> are wrapped in <font name='Mono'>&lt;source_document&gt;</font> tags with their document ID, version, "
                     "category and section IDs, so every answer can cite them. The <b>COVERAGE CHECKLIST</b> at the end lists the mandatory clause IDs the model "
                     "must cover - it is built from the clauses in this very request, not from the Python matrix, so Pipeline 2 stays independent.", "note", PW)

    # ------------------------------------------------------------------ 8
    story += [PageBreak()] + H1("8. Sample response")
    resp_pretty = pretty(sample["response"])
    story.append(P("The raw answer to the request in section 7, pretty-printed. The model returned one JSON object and nothing else.", "body"))
    story.append(kv([("Response size", f"{len(sample['response']):,} characters"), ("Status", "Accepted on the first attempt (schema-valid)"),
                     ("Modules in this response", str(len(extract_json(sample["response"])["modules"])))]))
    story += code(resp_pretty, label="response  ·  first part", width_chars=108, size=7.1, max_lines=125)
    story.append(P("Across the whole plan generation the capture made "
                   f"<b>{n['calls']}</b> requests ({n['prompt_chars_total']:,} characters of prompts sent, {n['response_chars_total']:,} characters of responses received; "
                   f"mean {n['avg_seconds']} s per request).", "body"))

    # ------------------------------------------------------------------ 9
    story += [PageBreak()] + H1("9. Structured JSON output")
    story.append(P("Free text is never the only output. Every response is parsed as JSON and validated against a Pydantic schema "
                   "(<font name='Mono'>schemas/plan_schema.py</font>) before it can enter a plan.", "body"))
    sch = bundle["schema"]
    story.append(P("Plan level: OnboardingPlan", "h3"))
    story.append(table([["Field", "Type", "Required", "Constraint"]] + schema_rows(sch, "OnboardingPlan"), [48 * mm, 72 * mm, 18 * mm, 36 * mm]))
    story.append(P("Module level", "h3"))
    story.append(table([["Field", "Type", "Required", "Constraint"]] + schema_rows(sch, "Module"), [48 * mm, 72 * mm, 18 * mm, 36 * mm]))
    story.append(P("Every checklist item, task and quiz question also carries <font name='Mono'>source_document_id</font> and "
                   "<font name='Mono'>source_section_id</font> - the mandatory link back to a source clause that Pipeline 2 later verifies.", "small"))
    story.append(P("A validated module (first module of the plan)", "h2"))
    story += code(json.dumps(n["first_module"], indent=2, ensure_ascii=False, default=str), label="module M01  ·  after schema validation", width_chars=108, size=7.1, max_lines=95)
    sc = n["validation"]["scores"]
    story.append(P("What happened to the whole plan", "h2"))
    story.append(table([["Measure", "Value"],
                        ["Plan ID", n["plan_id"]], ["Requests / batches", f"{n['calls']} / {n['batches']}"], ["Modules in the merged plan", str(n["modules"])],
                        ["Mandatory coverage (Python)", f"{sc['coverage']}%  ({sc['mandatory_covered']} of {sc['mandatory_expected']} mandatory requirements)"],
                        ["Source traceability (Python)", f"{sc['traceability']}%"], ["Contradictions found", str(sc["contradiction_count"])],
                        ["Hallucination flags", str(sc["hallucination_flags"])], ["Pipeline 2 verdict", n["validation"]["status"]]],
                       [70 * mm, 104 * mm]))
    story.append(Spacer(1, 6))
    story += callout("Reading the verdict", f"Pipeline 2 returned <b>{esc(n['validation']['status'])}</b>: {sc['contradiction_count']} statements disagree across the role's sources "
                     "(the document set deliberately contains conflicts, see the Company Document Dataset). A plan in this state cannot be approved silently - "
                     "it goes to a reviewer. This is the point of the two-pipeline design: the AI writes, Python checks.", "note", PW)

    # ------------------------------------------------------------------ 10
    story += [PageBreak()] + H1("10. Failure examples")
    story.append(P("A healthy API does not fail on demand, so the four failures below were <b>provoked deliberately</b> by wrapping the client and "
                   "corrupting one answer. They pass through the real retry, validation and logging code, so the log lines and messages are the real ones.", "body"))
    story.append(table([["#", "Failure", "How it was provoked", "What the code did"],
                        ["F1", "Reply is not JSON", "Client returns prose with a broken JSON fragment", "Rejected by the JSON extractor; logged; retried"],
                        ["F2", "JSON that breaks the schema", "A real response with an illegal category and no covered requirements", "Rejected by Pydantic; logged with the exact fields; retried"],
                        ["F3", "Every attempt fails", "Three bad replies in a row", f"Stopped after {cfg['GENAI_MAX_RETRIES']} attempts; reported, never an endless loop"],
                        ["F4", "A request outruns the time budget", f"One request delayed for {bg.get('hang', 9)} s with a {bg['budget']} s budget", "Plan returned on time without it; the gap is reported"]],
                       [10 * mm, 42 * mm, 62 * mm, 60 * mm]))
    l1, l2 = rt["logs"][0], rt["logs"][1]
    story.append(P("F1 - the reply is not JSON", "h2"))
    story += code(json.dumps({k: l1.get(k) for k in ("purpose", "attempt", "model", "prompt_chars", "ok", "seconds", "error")}, indent=2), label="generation log entry  ·  attempt 1")
    story.append(P("F2 - JSON that violates the schema", "h2"))
    story += code(l2.get("error", ""), label="Pydantic error captured in the generation log  ·  attempt 2", width_chars=108)
    story.append(P("F3 - retries exhausted", "h2"))
    story += code(ex["message"], label="GenerationFailed raised to the caller")
    story.append(P("The plan-generation code catches this per request: a failed batch is listed in <font name='Mono'>insufficient_information</font> and the rest of the "
                   "plan is still produced. The reviewer then uses <b>Add missing requirements</b> to fill the gap. Nothing fails silently.", "small"))
    story.append(P("F4 - time budget exceeded", "h2"))
    story.append(table([["Time budget", "Plan returned after", "Requests that did not finish", "Modules still delivered"],
                        [f"{bg['budget']} s", f"{bg['seconds']} s", str(bg["late"]), str(bg["modules"])]], [40 * mm, 44 * mm, 50 * mm, 40 * mm]))
    for note in bg["notes"]:
        story += code(note, label="reported back to the reviewer")
    story.append(P("Failures the client handles that were not provoked here", "h2"))
    story.append(table([["Situation", "Handling in genai_pipeline/client.py and generator.py"],
                        ["Invalid key, quota, network error, unknown model, API timeout", "Wrapped as GenAIError with the class name and first 300 characters; logged; retried"],
                        ["Output cut off (finish_reason = length)", "Raised as an error so a truncated JSON is never parsed; retried"],
                        ["Empty or filtered response", "Raised as an error; logged; retried"],
                        ["API key not configured", "Reported at once; no retry (retrying cannot fix a missing key)"],
                        ["Answer wrapped in a markdown fence or preamble", "The JSON extractor strips it before validation"]],
                       [70 * mm, 104 * mm]))

    # ------------------------------------------------------------------ 11
    story += [PageBreak()] + H1("11. Retry evidence")
    story.append(P("The same real request from section 7 was replayed through <font name='Mono'>call_with_retry</font> with two provoked failures ahead of a good answer. "
                   "The table is the generation log exactly as the application stored it (also visible in each plan's <b>Generation log</b> tab).", "body"))
    rows = [["Attempt", "Result", "Prompt chars", "Seconds", "What the validator said"]]
    for l in rt["logs"]:
        err = (l.get("error") or "").replace("\n", " ")
        rows.append([str(l["attempt"]), "Accepted" if l["ok"] else "Rejected", f"{l.get('prompt_chars', 0):,}", str(l.get("seconds", "")),
                     (err[:150] + ("..." if len(err) > 150 else "")) if err else "Valid against the schema"])
    story.append(table(rows, [16 * mm, 20 * mm, 24 * mm, 16 * mm, 98 * mm]))
    story.append(Spacer(1, 6))
    story.append(P("Note how <b>Prompt chars</b> grows with each retry: the validator's message is appended to the prompt, so the model is told exactly what was wrong.", "small"))
    story.append(P("Feedback appended to the prompt before attempt 3", "h2"))
    fb = rt["feedback_attempt3"]
    story += code(fb[fb.find("YOUR PREVIOUS ANSWER"):] if "YOUR PREVIOUS ANSWER" in fb else fb, label="last part of the prompt sent on attempt 3", width_chars=108)
    story.append(P("Retry rules", "h2"))
    story += bullets([f"At most <b>{cfg['GENAI_MAX_RETRIES']}</b> attempts per request (<font name='Mono'>GENAI_MAX_RETRIES</font>); after that the failure is raised - never an infinite loop.",
                      "Back-off between attempts: 2 s, 4 s, 8 s (skipped in tests, and skipped when it would pass the time budget).",
                      "Retries never run past the plan's time budget: near the deadline the request is abandoned and reported.",
                      "Every attempt - accepted or rejected - is stored in <font name='Mono'>generation_logs</font> with time, model, prompt size, duration and error.",
                      "A retry cannot fix a missing API key, so that case stops immediately."])
    story.append(P("Retries exhausted: the three log rows", "h2"))
    story.append(table([["Attempt", "Result", "Error (short)"]] +
                       [[str(l["attempt"]), "Rejected", (l.get("error") or "").replace("\n", " ")[:110]] for l in ex["logs"]], [20 * mm, 22 * mm, 132 * mm]))
    tr = bundle.get("tests")
    story.append(P("Automated proof", "h2"))
    story.append(P("These behaviours are asserted by the project's test suite (<font name='Mono'>tests/test_genai_and_validation.py</font>):", "body"))
    story.append(table([["Test", "Asserts"],
                        ["test_schema_rejects_bad_json", "Malformed plans never validate"],
                        ["test_retry_recovers_from_invalid_json", "A bad reply is retried and the plan is still produced"],
                        ["test_retry_limit_is_enforced", "Retries stop at the configured limit"],
                        ["test_plan_is_generated_in_batches_with_unique_ids", "Batches merge into one plan without ID clashes"],
                        ["test_time_budget_returns_on_time_even_if_a_request_hangs", "A hanging request cannot hold the plan past its budget"],
                        ["test_regenerate_modules_runs_in_parallel_within_time_budget", "Regeneration of several modules finishes inside its budget"]],
                       [92 * mm, 82 * mm], col_style={0: "cellm"}))
    if tr:
        story.append(Spacer(1, 4))
        story.append(P(f"Result of running these tests while building this document: <b>{esc(tr)}</b>.", "small"))

    # ------------------------------------------------------------------ 12
    story += H1("12. Reproducing this evidence")
    story += code("python -m pip install -r requirements.txt\n"
                  "python -m src.evidence.build_genai_evidence            # offline stand-in (no key, no cost)\n"
                  "python -m src.evidence.build_genai_evidence --live     # real API from .env - use this for the final submission\n"
                  "python -m src.evidence.build_genai_evidence --rebuild  # re-draw the PDF from the last capture", label="commands")
    story.append(table([["File", "Content"],
                        ["reports/Deliverable_4_GenAI_Pipeline_Evidence.pdf", "This document"],
                        ["documentation/evidence/genai_capture.json", "Raw capture: prompts, responses, logs, failure runs, schema"],
                        ["prompt_templates/*.yaml", "The versioned prompt templates"],
                        ["genai_pipeline/client.py", "API clients (OpenAI, Gemini)"],
                        ["genai_pipeline/generator.py", "Batching, retry, time budget, merging"],
                        ["schemas/plan_schema.py", "Pydantic JSON schema"]], [80 * mm, 94 * mm], col_style={0: "cellm"}))

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    doc = ReportDoc(OUT, "GenAI Pipeline Evidence - SkillSprint AI", "Deliverable 4  ·  GenAI Pipeline Evidence", cover)
    doc.multiBuild(story)
    print("written", OUT)


def run_tests():
    try:
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "tests/test_genai_and_validation.py", "-k",
                            "retry or time_budget or schema or batches or regenerate"], cwd=ROOT, capture_output=True, text=True, timeout=240)
        last = [l for l in r.stdout.strip().splitlines() if l.strip()][-1]
        return last
    except Exception:
        return None


if __name__ == "__main__":
    if "--rebuild" in sys.argv:
        bundle = json.load(open(BUNDLE, encoding="utf-8"))
    else:
        bundle = capture_genai.capture("--live" in sys.argv)
    bundle["tests"] = run_tests()
    build(bundle)
