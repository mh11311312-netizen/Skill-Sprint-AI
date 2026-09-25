# Sitara Bank Ltd. — Company Profile and Organisational Scenario

*Fictional organisation created for the SkillSprint AI project (Aptech Generative AI PowerPlay, theme OnboardVerse). All names, figures and rules are invented.*

## 1. Company Profile

| Item | Detail |
|---|---|
| Company | Sitara Bank Ltd. |
| Industry | Retail banking |
| Headquarters | Karachi, Pakistan |
| Network | 40 branches in Karachi, Lahore, Islamabad and other cities |
| Employees | About 2,500 |
| Core values | Integrity, Customer First, Accountability, Security |

## 2. Organisational Scenario

Sitara Bank is expanding its branch network and hires about 40 new employees every month. Onboarding is currently handled manually by HR and branch managers using scattered policies, SOPs and FAQs. Several documents have been updated in 2026, but older FAQs and handbooks were not revised, so new joiners often receive conflicting instructions (for example on leave notice, password rules and complaint escalation times). Regulators expect customer-facing staff to complete AML and KYC training quickly and to be able to prove it. The bank wants SkillSprint AI to create personalised, source-traceable onboarding plans for every role and to detect outdated, conflicting or unsupported content automatically.

## 3. Departments

Retail Banking, Customer Service, Human Resources, Finance, Operations, Information Technology, Compliance, Marketing, Data and Analytics.

## 4. Job Roles (12)

| Role ID | Role | Department |
|---|---|---|
| ROLE-01 | Branch Manager | Retail Banking |
| ROLE-02 | Customer Service Officer | Customer Service |
| ROLE-03 | Sales Executive | Retail Banking |
| ROLE-04 | HR Executive | Human Resources |
| ROLE-05 | Finance Associate | Finance |
| ROLE-06 | Operations Coordinator | Operations |
| ROLE-07 | IT Support Engineer | Information Technology |
| ROLE-08 | Compliance Officer | Compliance |
| ROLE-09 | Marketing Executive | Marketing |
| ROLE-10 | Data Analyst | Data and Analytics |
| ROLE-11 | Cash Teller | Retail Banking |
| ROLE-12 | Team Leader | Operations |

## 5. Active Document Collection (21 documents)

| Doc ID | Title | Category | Department | Version | Effective Date |
|---|---|---|---|---|---|
| CMP-01 | Mandatory Compliance Training Requirements | Compliance | Compliance | 2.0 | 2026-07-01 |
| FAQ-01 | HR and Leave FAQ | FAQ | Human Resources | 1.0 | 2025-08-15 |
| FAQ-02 | IT and Security FAQ | FAQ | Information Technology | 1.0 | 2025-06-10 |
| POL-01 | Employee Handbook | Handbook | Human Resources | 1.0 | 2025-07-01 |
| POL-02 | HR Policy | Policy | Human Resources | 2.0 | 2026-01-01 |
| POL-03 | Leave Policy | Policy | Human Resources | 2.0 | 2026-04-01 |
| POL-04 | Information Security Policy | Policy | Information Technology | 2.0 | 2026-03-01 |
| POL-05 | Workplace Conduct Policy | Policy | Human Resources | 1.0 | 2025-09-01 |
| POL-06 | Data Privacy Policy | Policy | Compliance | 2.0 | 2026-05-01 |
| POL-07 | AML and KYC Compliance Policy | Policy | Compliance | 2.0 | 2026-02-01 |
| POL-08 | Fraud Prevention and Whistleblowing Policy | Policy | Compliance | 1.0 | 2025-11-01 |
| PRC-01 | New Joiner Process Manual | Process Manual | Human Resources | 1.0 | 2026-01-05 |
| RD-01 | Role Descriptions | Role Description | Human Resources | 1.0 | 2025-12-01 |
| SOP-01 | Customer Complaint Handling Procedure | SOP | Customer Service | 1.0 | 2025-05-01 |
| SOP-02 | Escalation Procedure | SOP | Operations | 2.0 | 2026-06-15 |
| SOP-03 | Account Opening and KYC Procedure | SOP | Retail Banking | 2.0 | 2026-02-15 |
| SOP-04 | Cash Handling and Vault Procedure | SOP | Operations | 2.0 | 2026-04-15 |
| SOP-05 | IT Incident and Access Request Procedure | SOP | Information Technology | 2.0 | 2026-05-15 |
| SOP-06 | Expense and Payment Processing Procedure | SOP | Finance | 1.0 | 2025-08-01 |
| SOP-07 | Marketing Content Approval Procedure | SOP | Marketing | 1.0 | 2025-10-01 |
| SOP-08 | Data Access and Reporting Procedure | SOP | Data and Analytics | 1.0 | 2026-01-10 |

Additional files: 10 superseded v1.0 documents (`documents/superseded`) and 5 adversarial documents (`documents/adversarial`).

## 6. Document Precedence Hierarchy

1. Policy
2. Compliance requirement document
3. SOP
4. Employee Handbook
5. Role Description
6. Process Manual
7. FAQ
8. Guideline / Informal Guidance (cannot create or override requirements)

Rules: only Active versions are used; lower level wins; at the same level the later effective date wins; a specific rule for a named role or module applies within its own scope; unresolved cases go to manual review. Machine-readable version: `data/precedence_rules.yaml`.

## 7. Dataset Statistics vs SRS Minimums

| SRS requirement | Minimum | This pack |
|---|---|---|
| Company documents | 20 | 21 active (+10 superseded, +5 adversarial) |
| Job roles | 10 | 12 |
| Identifiable requirements | 150 | 228 (221 active after conflict resolution) |
| Mandatory requirements | 50 | 186 |
| Role-specific requirements | 30 | 138 |
| Conflicting / ambiguous cases | 10 | 14 (`data/conflict_cases.csv`) |
| Policy-version changes | 10 | 10 documents, 20 changed clauses (`data/version_history.csv`) |
| Adversarial / prompt-injection cases | 10 | 10 (`data/adversarial_cases.csv`) |

## 8. Document Writing Conventions (what the parser can rely on)

Each document starts with a Document Control table (ID, title, category, department, version, status, effective date, review date, owner, supersedes). Sections use numbered headings (`2. Security Awareness`) followed by an `Applies to:` line listing roles or `All employees`. Each numbered clause (`2.1`, `2.2` ...) contains at most one requirement. A clause may end with `(Applies to: Role)` to narrow its scope.

## 9. Rules Used to Build the Reference Requirement Matrix

Requirement ID = `DocumentID-ClauseNumber` (for example `POL-04-3.2`).

Obligation: `must / shall / required / mandatory` → Mandatory; `should / recommended / encouraged` → Recommended; `may` → Optional; none of these → Informational (not a requirement).

Requirement type: acknowledge / sign / declare → Must Acknowledge; demonstrate → Must Demonstrate; complete / attend / submit / pass / enable / collect → Must Complete; other mandatory → Must Know.

Due stage: "Day 1" → Day 1; "first week of joining" → Week 1; "within N days of joining" → Week 1 (≤7), Week 2 (≤14), First 30 Days (≤30), First 60 Days (≤60), First 90 Days (≤90); "end of probation" → First 90 Days. Otherwise default by category: Policy and Handbook → Week 1, SOP / Role Description / FAQ → Week 2, Compliance and Process Manual → First 30 Days.

Priority: Mandatory in Compliance-type documents (POL-04, POL-06, POL-07, POL-08, CMP-01) or due on Day 1 → High; other Mandatory → Medium; Recommended / Optional → Low.

Assessment: Must Demonstrate → Practical Assessment; Must Acknowledge → Signed Acknowledgement; other Mandatory → Knowledge Quiz; otherwise None.

Requirements overridden by a higher-precedence source are kept in `requirements_master.csv` with `include_in_active_matrix = No`.
