"""Sign in, sign up (employee account activation), first-login password change and sign out."""
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from database.db import get_db
from security.auth import check_password, hash_password
from src.audit import log_audit, log_security, now

bp = Blueprint("auth", __name__)

DEFAULT_EMPLOYEE_PASSWORD = "Employee@123"


def _safe_next(target):
    """Only allow redirects to pages of this site (blocks //other-site.com tricks)."""
    if target and target.startswith("/") and not target.startswith("//") and not target.startswith("/\\"):
        return target
    return None


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        user = get_db().users.find_one({"username": username})
        if user and check_password(request.form.get("password", ""), user["password"]):
            session.clear()
            session.update(username=user["username"], app_role=user["app_role"], employee_id=user.get("employee_id"))
            log_audit("login", "user", username, user=username)
            if user.get("must_change_password"):
                session["must_change_password"] = True
                flash("Please choose a new password before you continue.", "info")
                return redirect(url_for("auth.change_password"))
            return redirect(_safe_next(request.args.get("next")) or url_for("main.home"))
        log_security("Failed login", f"username={username}", "Low")
        flash("Invalid username or password.", "danger")
    return render_template("login.html")


@bp.route("/signup", methods=["GET", "POST"])
def signup():
    """A new employee activates their account with their Employee ID and joining date from HR records."""
    if request.method == "POST":
        db = get_db()
        employee_id = request.form.get("employee_id", "").strip().upper()
        joining_date = request.form.get("joining_date", "").strip()
        employee = db.employees.find_one({"employee_id": employee_id}) if employee_id else None
        if not employee_id or not joining_date:
            flash("Enter your Employee ID and joining date.", "danger")
        elif not employee or employee.get("joining_date") != joining_date:
            # same message for both cases, so the form cannot be used to discover valid employee IDs
            log_security("Failed sign-up", f"employee_id={employee_id}", "Low")
            flash("We could not match these details with HR records. Check your Employee ID and joining date, or contact HR.", "danger")
        elif db.users.find_one({"$or": [{"employee_id": employee_id}, {"username": employee_id.lower()}]}):
            flash(f"An account for {employee_id} already exists. Sign in with username {employee_id.lower()}.", "warning")
            return redirect(url_for("auth.login"))
        else:
            db.users.insert_one({"username": employee_id.lower(), "password": hash_password(DEFAULT_EMPLOYEE_PASSWORD),
                                 "app_role": "employee", "employee_id": employee_id, "must_change_password": True,
                                 "created_at": now(), "created_via": "sign-up"})
            log_audit("sign_up", "user", employee_id.lower(), after="employee", user=employee_id.lower())
            flash(f"Account created. Sign in with username {employee_id.lower()} and password {DEFAULT_EMPLOYEE_PASSWORD}. "
                  "You will be asked to choose your own password.", "success")
            return redirect(url_for("auth.login"))
    return render_template("signup.html")


@bp.route("/change-password", methods=["GET", "POST"])
def change_password():
    if "username" not in session:
        return redirect(url_for("auth.login"))
    if request.method == "POST":
        db = get_db()
        user = db.users.find_one({"username": session["username"]})
        current, new, confirm = (request.form.get(k, "") for k in ("current_password", "new_password", "confirm_password"))
        if not user or not check_password(current, user["password"]):
            flash("Your current password is not correct.", "danger")
        elif len(new) < 8 or new.isalpha() or new.isdigit():
            flash("The new password must have at least 8 characters, with letters and numbers.", "danger")
        elif new == current or new == DEFAULT_EMPLOYEE_PASSWORD:
            flash("Choose a password different from the default one.", "danger")
        elif new != confirm:
            flash("The two new passwords do not match.", "danger")
        else:
            db.users.update_one({"_id": user["_id"]}, {"$set": {"password": hash_password(new)}, "$unset": {"must_change_password": ""}})
            session.pop("must_change_password", None)
            log_audit("change_password", "user", user["username"], user=user["username"])
            flash("Password changed.", "success")
            return redirect(url_for("main.home"))
    return render_template("change_password.html")


@bp.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))
