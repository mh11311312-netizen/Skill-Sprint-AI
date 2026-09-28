"""Employee sign-up (account activation) and the forced first-login password change."""
from src.audit import now


def _new_employee(ctx):
    if not ctx.employees.find_one({"employee_id": "EMP-099"}):
        ctx.employees.insert_one({"employee_id": "EMP-099", "full_name": "Test Joiner", "role": "Cash Teller",
                                  "department": "Retail Banking", "joining_date": "2026-09-20", "created_at": now()})


def test_signup_needs_matching_joining_date(client, ctx):
    _new_employee(ctx)
    r = client.post("/signup", data={"employee_id": "EMP-099", "joining_date": "2026-01-01"}, follow_redirects=True)
    assert b"could not match" in r.data and not ctx.users.find_one({"employee_id": "EMP-099"})
    r = client.post("/signup", data={"employee_id": "EMP-404", "joining_date": "2026-09-20"}, follow_redirects=True)
    assert b"could not match" in r.data                     # unknown ID gets the same message


def test_signup_then_forced_password_change(client, ctx):
    _new_employee(ctx)
    client.get("/logout")
    r = client.post("/signup", data={"employee_id": "emp-099", "joining_date": "2026-09-20"}, follow_redirects=True)
    assert b"Account created" in r.data
    user = ctx.users.find_one({"username": "emp-099"})
    assert user["app_role"] == "employee" and user["must_change_password"]
    # signing up twice is refused
    r = client.post("/signup", data={"employee_id": "EMP-099", "joining_date": "2026-09-20"}, follow_redirects=True)
    assert b"already exists" in r.data
    # first login goes to the password page and other pages are blocked until it is changed
    r = client.post("/login", data={"username": "emp-099", "password": "Employee@123"})
    assert r.headers["Location"].endswith("/change-password")
    assert client.get("/learner/").headers["Location"].endswith("/change-password")
    r = client.post("/change-password", data={"current_password": "Employee@123", "new_password": "Employee@123",
                                              "confirm_password": "Employee@123"}, follow_redirects=True)
    assert b"different from the default" in r.data
    r = client.post("/change-password", data={"current_password": "Employee@123", "new_password": "Sitara2026",
                                              "confirm_password": "Sitara2026"})
    assert r.status_code == 302 and client.get("/learner/").status_code == 200
    assert "must_change_password" not in ctx.users.find_one({"username": "emp-099"})


def test_login_redirect_cannot_leave_the_site(client):
    client.get("/logout")
    r = client.post("/login?next=//evil.example.com", data={"username": "admin", "password": "Admin@123"})
    assert r.headers["Location"] == "/"
