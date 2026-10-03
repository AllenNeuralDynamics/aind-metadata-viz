"""Pydantic models for CRediT authorship contributions."""

from enum import Enum
import re
from typing import List, Optional, Union
from datetime import date

from aind_data_schema.components.identifiers import Person
from pydantic import BaseModel, Field, field_validator, model_validator


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
    """Legacy degree values retained for callers using the original levels."""

    LEAD = "lead"
    SUPPORTING = "supporting"
    EQUAL = "equal"


WorkflowLevelValue = Union[ContributionLevel, str]


class AuthorWorkflowLevel(BaseModel):
    """A configurable contribution level offered by the author workflow."""

    value: str = Field(description="Stable value stored on a contribution")
    label: str = Field(description="Level label shown to contributors")
    description: str = Field(default="", description="Level definition shown in the add workflow")
    color: str = Field(default="#818cf8", description="Hex color used to display the level")
    enabled: bool = Field(default=True, description="Whether contributors may select this level")

    @field_validator("value", "label")
    @classmethod
    def require_non_empty_text(cls, value):
        if not value.strip():
            raise ValueError("value and label must not be empty")
        return value.strip()

    @field_validator("value")
    @classmethod
    def validate_stable_value(cls, value):
        if value == "none":
            raise ValueError("none is reserved for an empty contribution")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", value):
            raise ValueError("value must be a lowercase identifier")
        return value

    @field_validator("color")
    @classmethod
    def validate_hex_color(cls, value):
        if len(value) != 7 or not value.startswith("#"):
            raise ValueError("color must be a six-digit hex color")
        try:
            int(value[1:], 16)
        except ValueError as exc:
            raise ValueError("color must be a six-digit hex color") from exc
        return value.lower()


DEFAULT_AUTHOR_WORKFLOW_LEVELS = (
    {
        "value": "supporting",
        "label": "+",
        "description": "indicates a supporting contribution, which may not warrant authorship",
        "color": "#9ca3af",
    },
    {
        "value": "equal",
        "label": "++",
        "description": "indicates a major contribution to a specific CRediT role",
        "color": "#818cf8",
    },
    {
        "value": "lead",
        "label": "Lead",
        "description": "indicates that the author was both a major contributor and the primary coordinator of this CRediT role, not all papers have authors at the lead level",
        "color": "#4338ca",
    },
)


class AuthorLevel(str, Enum):
    """Publication authorship position"""

    FIRST = "first"
    SENIOR = "senior"


class RoleContribution(BaseModel):
    """A single CRediT role paired with a contribution level."""

    role: CreditRole
    level: WorkflowLevelValue = Field(description="Configured author workflow level value")
    description: Optional[str] = Field(
        default=None, description="Optional free-text description"
    )
    linked_assets: Optional[List[str]] = Field(
        default=None,
    )
    linked_sections: Optional[List[str]] = Field(
        default=None,
        description="Optional list of paper sections this role contributed to",
    )
    start_date: Optional[date] = Field(
        default=None,
        description="Optional date when work on this role started",
    )
    end_date: Optional[date] = Field(
        default=None,
        description="Optional date when work on this role ended",
    )

    @field_validator("level", mode="before")
    @classmethod
    def preserve_builtin_level_enum(cls, value):
        if isinstance(value, ContributionLevel):
            return value
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                raise ValueError("level must not be empty")
            try:
                return ContributionLevel(stripped)
            except ValueError:
                return stripped
        return value

    @field_validator("level")
    @classmethod
    def require_non_empty_level(cls, value):
        if not str(value).strip():
            raise ValueError("level must not be empty")
        return value

    @model_validator(mode="after")
    def check_dates(self):
        if self.end_date is not None:
            if self.start_date is None:
                raise ValueError("end_date requires start_date")
            if self.end_date < self.start_date:
                raise ValueError("end_date must not be before start_date")
        return self


class SectionContribution(BaseModel):
    """A contribution to a specific section of a paper."""

    section: str = Field(description="Name of the paper section (e.g. Introduction, Methods)")
    description: Optional[str] = Field(default=None, description="Optional free-text description of the contribution")
    level: WorkflowLevelValue = Field(description="Configured author workflow level value")

    @field_validator("level", mode="before")
    @classmethod
    def preserve_builtin_level_enum(cls, value):
        if isinstance(value, ContributionLevel):
            return value
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                raise ValueError("level must not be empty")
            try:
                return ContributionLevel(stripped)
            except ValueError:
                return stripped
        return value

    @field_validator("level")
    @classmethod
    def require_non_empty_level(cls, value):
        if not str(value).strip():
            raise ValueError("level must not be empty")
        return value


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
    publication_order: Optional[int] = Field(
        default=None,
        description=(
            "Optional 1-based position of this author in the publication byline. "
            "When no contributor has a publication_order the ordering is "
            "considered unset and display paths fall back to their own default."
        ),
    )
    start_date: Optional[date] = Field(
        default=None,
        description="Optional date when the author started working on the project",
    )
    end_date: Optional[date] = Field(
        default=None,
        description="Optional date when the author stopped working on the project",
    )
    credit_levels: List[RoleContribution] = Field(default_factory=list)
    section_levels: List[SectionContribution] = Field(default_factory=list)
    from_asset: bool = Field(
        default=False,
        description="True when an author is listed in the metadata of a data asset",
    )
    is_admin: bool = Field(
        default=False,
        description=(
            "True when this contributor is a project admin. Admins may edit the "
            "whole project (every author row) and grant admin to others. The "
            "creator of a project is made an admin automatically; edit access "
            "for everyone else is gated by matching their logged-in ORCID iD to "
            "this contributor's registry_identifier."
        ),
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
    doi: List[str] = Field(
        default_factory=list,
        description=(
            "DOIs associated with this set of contributions. A project may be "
            "published in more than one venue, so this is a list. Legacy "
            "documents storing a single string (or null) are coerced on read."
        ),
    )

    @field_validator("doi", mode="before")
    @classmethod
    def coerce_doi_list(cls, value):
        """Accept the legacy scalar/null form and normalise it to a list."""
        if value is None:
            return []
        if isinstance(value, str):
            return [value] if value.strip() else []
        return value
    assets: List[str] = Field(default_factory=list, description="List of asset names associated with the project")
    edit_locked: bool = Field(
        default=False,
        description=(
            "Admin-controlled edit lock. When True, no contributor may add or "
            "modify entries; only a project admin (or global admin) can edit, "
            "and only an admin can toggle this flag off to unlock."
        ),
    )
    show_sections: bool = Field(default=False, description="Whether to show section contributions in the interface")
    show_levels: bool = Field(default=True, description="Whether to show CRediT contribution levels in the interface")
    show_timeline: bool = Field(default=False, description="Whether to show author timelines in the interface")
    allow_lead: bool = Field(default=True, description="Whether to allow designation of lead authors in the interface")
    allow_levels: bool = Field(default=True, description="Whether to allow designation of CRediT contribution levels in the interface")
    author_workflow_levels: Optional[List[AuthorWorkflowLevel]] = Field(
        default=None,
        description=(
            "Optional custom author workflow levels. When omitted, the interface "
            "uses its default +, ++ and Lead definitions; enabled=false keeps an "
            "option defined but unavailable to contributors."
        ),
    )

    @field_validator("author_workflow_levels")
    @classmethod
    def require_unique_workflow_level_values(cls, levels):
        if levels is None:
            return levels
        values = [level.value.casefold() for level in levels]
        if len(values) != len(set(values)):
            raise ValueError("author workflow level values must be unique")
        return levels

    @model_validator(mode="after")
    def fill_default_author_workflow_levels(self):
        if self.author_workflow_levels is None:
            self.author_workflow_levels = [
                AuthorWorkflowLevel(
                    **definition,
                    enabled=self.allow_levels and (self.allow_lead or definition["value"] != "lead"),
                )
                for definition in DEFAULT_AUTHOR_WORKFLOW_LEVELS
            ]
        return self
