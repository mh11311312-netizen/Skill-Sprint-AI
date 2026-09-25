"""Creates starter users, roles and employees.  Run once:  python -m src.seed
Roles and employee profiles are organisational data (not generated output), so seeding them is allowed.
Requirements are NEVER seeded - they are always extracted from uploaded documents."""
import csv
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from security.auth import hash_password
from src.audit import now

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "sample_documents", "Sitara_Bank_Company_Pack", "data")

DEFAULT_USERS = [
    ("admin", "Admin@123", "admin", None),
    ("trainer", "Trainer@123", "training_manager", None),
    ("reviewer", "Reviewer@123", "reviewer", None),
    ("evaluator", "Evaluator@123", "admin", None),
]


def seed(db, with_samples=True):
    for u, p, r, e in DEFAULT_USERS:
        if not db.users.find_one({"username": u}):
            db.users.insert_one({"username": u, "password": hash_password(p), "app_role": r,
                                 "employee_id": e, "created_at": now()})
    if not with_samples:
        return
    roles_csv, emp_csv = os.path.join(DATA, "roles.csv"), os.path.join(DATA, "employees.csv")
    if os.path.exists(roles_csv):
        for r in csv.DictReader(open(roles_csv, encoding="utf-8-sig")):
            db.roles.update_one({"name": r["role"]}, {"$setOnInsert": {
                "role_id": r["role_id"], "name": r["role"], "department": r["department"],
                "default_level": r["default_level"], "description": r["description"], "created_at": now()}}, upsert=True)
    if os.path.exists(emp_csv):
        for e in csv.DictReader(open(emp_csv, encoding="utf-8-sig")):
            db.employees.update_one({"employee_id": e["employee_id"]}, {"$setOnInsert": {
                "employee_id": e["employee_id"], "full_name": e["full_name"], "role": e["role"],
                "department": e["department"], "experience_level": e["experience_level"], "location": e["location"],
                "joining_date": e["joining_date"], "reporting_manager": e["reporting_manager"],
                "previous_experience": e["previous_experience"], "training_status": "Not Started",
                "created_at": now()}}, upsert=True)
            uname = e["employee_id"].lower()
            if not db.users.find_one({"username": uname}):
                db.users.insert_one({"username": uname, "password": hash_password("Employee@123"),
                                     "app_role": "employee", "employee_id": e["employee_id"], "created_at": now()})


if __name__ == "__main__":
    from app import create_app
    from database.db import get_db
    app = create_app()
    with app.app_context():
        seed(get_db())
        print("Seed complete. Log in with admin / Admin@123")
