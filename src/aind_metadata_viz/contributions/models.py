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


class AuthorLevel(str, Enum):
    """Publication authorship position"""

    FIRST = "first"
    SENIOR = "senior"


class RoleContribution(BaseModel):
    """A single CRediT role paired with a contribution level."""

    role: CreditRole
    level: ContributionLevel
    description: Optional[str] = Field(
        default=None, description="Optional free-text description"
    )
    linked_assets: Optional[List[str]] = Field(
        default=None,
    )


class SectionContribution(BaseModel):
    """A contribution to a specific section of a paper."""

    section: str = Field(description="Name of the paper section (e.g. Introduction, Methods)")
    description: Optional[str] = Field(default=None, description="Optional free-text description of the contribution")
    level: ContributionLevel


class Author(Person):
    """A person with an affiliation, used for display purposes."""

    affiliation: List[str] = Field(default_factory=list, description="List of affiliations for the contributor")
    other_names: List[str] = Field(default_factory=list)
    email: Optional[str] = Field(default=None, description="Optional email address for the contributor")


class AuthorContribution(BaseModel):
    """One contributor with their CRediT roles."""

    author: Author
    author_level: Optional[AuthorLevel] = Field(
        default=None,
        description="Optional publication authorship position, used for display purposes (e.g. first, middle, senior)",
    )
    start_date: Optional[date] = Field(
        default=None,
        description="Optional date when the author started working on the project",
    )
    credit_levels: List[RoleContribution] = Field(default_factory=list)
    section_levels: List[SectionContribution] = Field(default_factory=list)
    from_asset: bool = Field(
        default=False,
        description="True when an author is listed in the metadata of a data asset",
    )
    
    
    @model_validator(mode="after")
    def check_from_asset(self):
        if not self.from_asset:
            if any(role.linked_assets for role in self.credit_levels):
                self.from_asset = True
        return self


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
    locked: bool = Field(default=False, description="Whether this project is password-protected")
