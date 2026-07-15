"""contributions — CRediT authorship contribution tracking.

Public API
----------
Models:
    CreditRole, ContributionLevel, RoleContribution,
    AuthorContribution, ProjectContributions

Serialization:
    to_json, from_json, to_yaml, from_yaml, load

Storage (S3-backed):
    store_contributions, get_contributions, set_project_password,
    verify_project_password, get_contributions_by_doi

Membership / tokens (ORCID edit access):
    list_members, is_member, add_member, remove_member, disable_token
"""

from .models import (
    AuthorContribution,
    ContributionLevel,
    CreditRole,
    ProjectContributions,
    RoleContribution,
)
from .serializers import from_json, from_yaml, load, to_json, to_yaml
from .store import (
    get_contributions,
    get_contributions_by_doi,
    list_all_projects,
    list_project_commits,
    set_project_password,
    store_contributions,
    create_token,
    lookup_token,
    consume_token,
    find_active_token,
    disable_token,
    verify_project_password,
    list_members,
    is_member,
    add_member,
    remove_member,
)

__all__ = [
    # models
    "CreditRole",
    "ContributionLevel",
    "RoleContribution",
    "AuthorContribution",
    "ProjectContributions",
    # serializers
    "to_json",
    "from_json",
    "to_yaml",
    "from_yaml",
    "load",
    # store
    "store_contributions",
    "get_contributions",
    "list_all_projects",
    "list_project_commits",
    "set_project_password",
    "verify_project_password",
    "get_contributions_by_doi",
    "create_token",
    "lookup_token",
    "consume_token",
    "find_active_token",
    "disable_token",
    "list_members",
    "is_member",
    "add_member",
    "remove_member",
]
