"""Global search across employees, roles, documents, requirements, plan modules and statuses."""
from conftest import login


def test_search_finds_each_kind(client):
    login(client, "admin", "Admin@123")
    assert b"EMP-002" in client.get("/search?q=Bilal").data
    assert b"Cash Teller" in client.get("/search?q=teller").data
    assert b"POL-04" in client.get("/search?q=Information Security").data
    assert b"Requirements" in client.get("/search?q=password").data


def test_search_is_safe_and_protected(client):
    login(client, "admin", "Admin@123")
    assert client.get("/search?q=.*(").status_code == 200          # regex characters are escaped
    assert b"at least 2" in client.get("/search?q=a").data
    login(client, "emp-001", "Employee@123")
    assert client.get("/search?q=Bilal").status_code == 403       # employees cannot search staff data


def test_roles_filter(client):
    login(client, "admin", "Admin@123")
    page = client.get("/roles/?search=teller").data
    assert b"Cash Teller" in page and b"Branch Manager" not in page
