"""Pydantic models for CRediT authorship contributions."""

from enum import Enum
from typing import List, Optional
from datetime import date

from aind_data_schema.components.identifiers import Person
from pydantic import BaseModel, Field, model_validator


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
    start_date: Optional[date] = Field(
        default=None,
        description="Optional start date for the contribution (e.g. when an author started working on the project)",
    )
    end_date: Optional[date] = Field(
        default=None,
        description="Optional end date for the contribution",
    )
    description: Optional[str] = Field(
        default=None, description="Optional free-text description"
    )
    linked_sections: Optional[List[str]] = Field(
        default=None,
        description="Optional list of paper headers/subheaders that the contribution is linked to (e.g. Introduction, Methods)",
    )

    @model_validator(mode="after")
    def check_dates(cls, values):
        start_date = values.get("start_date")
        end_date = values.get("end_date")
        if end_date and not start_date:
            raise ValueError("start_date is required if end_date is provided")
        if start_date and end_date and end_date < start_date:
            raise ValueError("end_date cannot be before start_date")
        return values


class Author(Person):
    """A person with an affiliation, used for display purposes."""

    affiliation: List[str] = Field(default_factory=list, description="List of affiliations for the contributor")
    email: Optional[str] = Field(default=None, description="Optional email address for the contributor")


class AuthorContribution(BaseModel):
    """One contributor with their CRediT roles."""

    author: Author
    credit_levels: List[RoleContribution] = Field(default_factory=list)


class ProjectContributions(BaseModel):
    """All contributor data for a project."""

    project_name: str = Field(..., description="Unique project identifier used as the storage key")
    contributors: List[AuthorContribution] = Field(default_factory=list)
    sections: List[str] = Field(
        default_factory=list,
        description="Publication sections that authors may have contributed to (e.g. Introduction, Methods)",
    )
    doi: Optional[str] = Field(default=None, description="Optional DOI associated with this set of contributions")
    assets: List[str] = Field(default_factory=list, description="List of asset names associated with the project")
