"""RBAC roles and distinct privileges."""

from enum import StrEnum


class Role(StrEnum):
    ADMIN = "admin"
    PROCUREMENT_LEAD = "procurement_lead"
    EVALUATOR = "evaluator"
    MODERATOR = "moderator"
    OBSERVER_AUDITOR = "observer_auditor"


# The anonymisation map is readable only with this explicit grant; no role
# implies it (CLAUDE.md). Every read of the map is individually audited (M6).
PRIVILEGE_ANONYMISATION_MAP_READ = "anonymisation_map.read"

KNOWN_PRIVILEGES = frozenset({PRIVILEGE_ANONYMISATION_MAP_READ})
