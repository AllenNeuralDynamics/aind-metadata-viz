"""Pydantic models for CRediT authorship contributions."""

from enum import Enum
from typing import List

from aind_data_schema.core.data_description import Person
from pydantic import BaseModel, Field


class CreditRole(str, Enum):
    """CRediT taxonomy roles (https://credit.niso.org/)."""

    CONCEPTUALIZATION = "conceptualization"
    DATA_CURATION = "data-curation"
    FORMAL_ANALYSIS = "formal-analysis"
    FUNDING_ACQUISITION = "funding-acquisition"
    INVESTIGATION = "investigation"
    METHODOLOGY = "methodology"
    PROJECT_ADMINISTRATION = "project-administration"
    RESOURCES = "resources"
    SOFTWARE = "software"
    SUPERVISION = "supervision"
    VALIDATION = "validation"
    VISUALIZATION = "visualization"
    WRITING_ORIGINAL_DRAFT = "writing-original-draft"
    WRITING_REVIEW_EDITING = "writing-review-editing"


class ContributionLevel(str, Enum):
    """Degree of contribution for a given CRediT role."""

    LEAD = "lead"
    SUPPORTING = "supporting"
    EQUAL = "equal"


class RoleContribution(BaseModel):
    """A single CRediT role paired with a contribution level."""

    role: CreditRole
    level: ContributionLevel


class AuthorContribution(BaseModel):
    """One contributor with their CRediT roles."""

    person: Person
    credit_levels: List[RoleContribution] = Field(default_factory=list)


class ProjectContributions(BaseModel):
    """All contributor data for a project."""

    project_name: str = Field(..., description="Unique project identifier used as the storage key")
    contributors: List[AuthorContribution] = Field(default_factory=list)
