"""contributions — CRediT authorship contribution tracking.

Public API
----------
Models:
    CreditRole, ContributionLevel, RoleContribution,
    AuthorContribution, ProjectContributions

Serialization:
    to_json, from_json, to_yaml, from_yaml, load

Storage (SQLite-backed):
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
from .store import get_contributions, list_project_commits, store_contributions
from .examples.defaults import IBL_PROJECT_NAME, ibl_default_contributions
from .examples.authorship_extractor import AUTHORSHIP_PROJECT_NAME, authorship_extractor_contributions
from .examples.authorship_extractor_real import AUTHORSHIP_REAL_PROJECT_NAME, authorship_extractor_real_contributions
from .examples.ibl_decision import IBL_DECISION_PROJECT_NAME, ibl_decision_contributions

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
    "list_project_commits",
    # defaults / examples
    "IBL_PROJECT_NAME",
    "ibl_default_contributions",
    "AUTHORSHIP_PROJECT_NAME",
    "authorship_extractor_contributions",
    "AUTHORSHIP_REAL_PROJECT_NAME",
    "authorship_extractor_real_contributions",
    "IBL_DECISION_PROJECT_NAME",
    "ibl_decision_contributions",
]
