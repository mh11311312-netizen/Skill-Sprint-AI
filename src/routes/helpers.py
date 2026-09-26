from datetime import datetime

STAFF = ("admin", "training_manager", "reviewer", "manager")
EDITORS = ("admin", "training_manager")
REVIEWERS = ("admin", "reviewer", "training_manager")

_CLASSES = {
    "ok": ["Verified", "Approved", "Active", "Trusted", "Completed", "On Track", "Resolved", "valid", "Both valid", "Yes"],
    "warn": ["Verified with Warning", "Partially Verified", "Pending Review", "Generated", "Assessment Required",
             "Suspicious", "Optional Not Included", "Medium", "Manual Review Required", "Outdated"],
    "bad": ["Contradictory", "Contradiction Detected", "Unsupported", "Unsupported Requirement", "Incomplete",
            "Requirement Missing", "Source Support Missing", "Outdated Source", "Rejected", "Untrusted",
            "Behind Schedule", "Requires Attention", "High", "missing", "outdated", "untrusted", "quarantined", "No", "Overdue"],
    "muted": ["Superseded", "Low", "Not Started", "-"],
}


def status_class(value):
    for cls, values in _CLASSES.items():
        if value in values:
            return f"stamp stamp-{cls}"
    return "stamp stamp-info"


def fmt_dt(value):
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    return value or ""
