"""Role x action matrix for tenant users (PRD.md "Users and roles"; UT-12; ASVS 8.2.1).

One table, checked by the console before every tenant action. The operator is not a tenant role:
operator actions are checked separately and never inside a tenant.
"""

from __future__ import annotations

ROLES = ("owner", "engineer", "reviewer")

# action -> roles allowed
MATRIX: dict[str, frozenset[str]] = {
    "project.read": frozenset({"owner", "engineer", "reviewer"}),
    "request_log.read": frozenset({"owner", "engineer", "reviewer"}),
    "report.read": frozenset({"owner", "engineer", "reviewer"}),
    "connection.write": frozenset({"owner", "engineer"}),
    "route.write": frozenset({"owner", "engineer"}),
    "key.write": frozenset({"owner", "engineer"}),
    "member.read": frozenset({"owner"}),
    "member.write": frozenset({"owner"}),
}


def allowed(role: str | None, action: str) -> bool:
    if action not in MATRIX:
        raise KeyError(f"unknown action {action!r}")
    return role in MATRIX[action]
