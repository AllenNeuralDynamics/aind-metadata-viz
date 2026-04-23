"""contributions — CRediT authorship contribution tracking.

Public API
----------
Models:
    CreditRole, ContributionLevel, RoleContribution,
    AuthorContribution, ProjectContributions

Serialization:
    to_json, from_json, to_yaml, from_yaml, load

Storage (git-backed):
    store_contributions, get_contributions
"""

from .models import (
    AuthorContribution,
    ContributionLevel,
    CreditRole,
    ProjectContributions,
    RoleContribution,
)
from .serializers import from_json, from_yaml, load, to_json, to_yaml
from .store import get_contributions, store_contributions

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
]
