Skillsprint

Skillsprint is a Flask web application that uses company documents to create personalised onboarding plans for employees based on their roles.

The application uses a GenAI model (OpenAI or Google Gemini) to generate the onboarding plan. After that, a separate Python validation pipeline checks the generated plan against the original company documents. This makes sure that the generated information is actually supported by the available sources.

For this project, a fictional company called Sitara Bank Ltd. (Karachi) is used as sample data.

The sample data contains:

21 active documents
10 superseded document versions
5 adversarial documents
12 roles
15 employees

All sample documents are available inside the sample_documents/ folder.

How it works

The project has two separate pipelines.

GenAI Pipeline

The first pipeline uses OpenAI or Google Gemini to generate an onboarding plan.

It takes:

Employee information
Employee role
Approved source clauses related to that role

The output is a structured JSON onboarding plan which is checked using Pydantic schemas.

Python Validation Pipeline

The second pipeline does not use AI.

It checks the generated plan against the uploaded company documents and the role requirements.

It checks things such as:

Whether the source actually exists
Whether the source is still active
Whether the requirement belongs to the employee's role
Whether numbers and dates are correct
Whether the generated content is supported by the source
Whether any requirements are missing
Whether there are contradictions
Whether quizzes have correct answers
Whether prerequisites and module ordering are correct
Whether duplicate requirements exist

The validation can produce statuses such as:

Verified
Verified with Warning
Partially Verified
Source Support Missing
Requirement Missing
Unsupported Requirement
Outdated Source
Contradiction Detected
Manual Review Required

The system also calculates different validation scores, including coverage, traceability, requirement consistency and generation consistency.

Document management

Documents can be uploaded as PDF or DOCX files.

The application checks:

File type
File size
Empty files
Duplicate files using SHA-256
Document metadata
Dates
Document versions

Only the active version of a document is used when generating plans. Older versions are kept so that they can be used for history and policy impact analysis.

Documents are also checked for possible security issues such as prompt injection and hidden text.

Role requirements

The Role Requirement Matrix is created using the rules stored in the config/ folder.

Requirements can contain information such as:

Obligation
Requirement type
Applicable roles
Onboarding stage
Priority
Assessment
Prerequisites

When different documents contain conflicting or duplicate requirements, the rules in config/precedence_rules.yaml are used to resolve them.

Human review

Generated plans can be reviewed before they are used.

Reviewers can:

Approve a plan
Reject a plan
Add comments
Edit modules
Override individual validation results
Regenerate selected modules

All important review actions are recorded in the audit trail.

Policy updates

When a new version of a policy is uploaded, the system can compare it with the previous version.

It identifies affected:

Plans
Modules
Quiz questions
Tasks

Only the affected parts can then be regenerated.

Hallucination checking

If a requested topic is not supported by the available company documents, the system does not simply generate information for it.

Instead, the request is sent for manual review.

This helps prevent the GenAI model from adding requirements that are not present in the company's documents.

Employee learning

Employees can log in and view their own onboarding plan.

They can access:

Learning modules
Checklists
Tasks
Quizzes
Progress
Weak areas
Recommendations
Dashboards and reports

The application includes separate dashboards for administrators, roles and employees.

There are also search and filtering options, plan comparison and reports that can be exported as:

CSV
Excel
PDF
Security

The application includes several security measures:

Password hashing with bcrypt
Role-based access
CSRF protection
Prompt-injection scanning
Hidden-text detection
Document quarantine
Source delimiters in GenAI prompts
Untrusted document handling
Setup

Open the project in VS Code and create a virtual environment:

python -m venv venv
venv\Scripts\activate

Install the required packages:

pip install -r requirements.txt

Create the environment file:

copy .env.example .env

Then update .env with the required values:

MONGO_URI
SECRET_KEY
GENAI_PROVIDER
OPENAI_API_KEY
GEMINI_API_KEY

Only the API key for the selected provider is required.

Create the initial users and employees:

python -m src.seed

Start the application:

python app.py

Open:

http://127.0.0.1:5000
Demo
Log in using the admin account.
Open Documents.
Upload the files from sample_documents/Sitara_Bank_Company_Pack/documents/active/pdf/.
Upload the superseded and adversarial documents as well.
Open Employees and select an employee.
Generate the personalised onboarding plan.
The Python validation pipeline will automatically check the generated plan.
Open the Review Queue to review the results.
Log in as an employee to test the learning plan.
Upload a newer version of a policy to test the Policy Impact feature.

MongoDB data can be viewed using MongoDB Compass with the same MONGO_URI.

The default database name is:

skillsprint
Demo accounts

These accounts are provided for testing.

admin / Admin@123 - Full access
trainer / Trainer@123 - Documents, roles, employees and generation
reviewer / Reviewer@123 - Review and approval
evaluator / Evaluator@123 - Evaluation/admin access
emp-001 to emp-015 / Employee@123 - Own learning plan

These passwords should be changed before using the application in a real environment.

Adding new documents and roles

The application is designed so that new documents and roles can be added without changing the main application code.

To test a new role:

Upload the required PDF or DOCX documents.
Add the role from the Roles section.
Add an employee with that role.
Generate the employee's plan.

The role requirement matrix will be rebuilt using the uploaded documents and configuration rules.

Unknown role names found in document "Applies to" sections can be checked from the Conflicts & Duplicates section.

More information about the hidden test setup is available in:

hidden_test_ready/README.md
Testing

Run the test suite with:

python -m pytest -q

The tests use mongomock instead of a real MongoDB server.

A local fake Gemini API is also used for testing. It can intentionally create mistakes such as:

Hallucinated requirements
Incorrect numbers
Outdated sources
Untrusted sources
Missing requirements
Incorrect quiz answers
Incorrect sequencing

The tests check that the Python validation pipeline is able to detect these problems.

The actual application uses the configured real GenAI API.

Deployment

The project includes a render.yaml file for deployment on Render with MongoDB Atlas.

The required environment variables need to be added to Render:

MONGO_URI
GENAI_PROVIDER
OPENAI_API_KEY
GEMINI_API_KEY

After deployment, the seed command can be run once from the Render shell:

python -m src.seed

MongoDB Atlas network access also needs to allow the Render server to connect.

Limitations

The validation system uses rules and TF-IDF similarity for some of its checks. These checks are useful for detecting many problems but they cannot guarantee that every possible contradiction or hallucination will be detected.

The validation thresholds are stored in:

config/validation_rules.yaml

Some contradictions that require deeper reasoning may not be detected.

Scanned image-only PDFs are currently rejected because OCR is not included.

The GenAI provider and model can be changed from .env without changing the application code.

For example:

GENAI_PROVIDER=openai
OPENAI_MODEL=...

or:

GENAI_PROVIDER=gemini
GEMINI_MODEL=...

