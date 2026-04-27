"""Real contributor data converted from AllenNeuralDynamics/AuthorshipExtractor authors-real.yml."""

from ..models import (
    Author,
    AuthorContribution,
    ContributionLevel,
    CreditRole,
    ProjectContributions,
    RoleContribution,
)

AUTHORSHIP_REAL_PROJECT_NAME = "authorship-extractor-real"

_lead = ContributionLevel.LEAD

_C = CreditRole.CONCEPTUALIZATION
_DC = CreditRole.DATA_CURATION
_ME = CreditRole.METHODOLOGY
_PA = CreditRole.PROJECT_ADMINISTRATION
_SW = CreditRole.SOFTWARE
_VA = CreditRole.VALIDATION
_VI = CreditRole.VISUALIZATION
_WO = CreditRole.WRITING_ORIGINAL_DRAFT
_WR = CreditRole.WRITING_REVIEW_EDITING


def _rc(role: CreditRole, level: ContributionLevel) -> RoleContribution:
    return RoleContribution(role=role, level=level)


def authorship_extractor_real_contributions() -> ProjectContributions:
    """Return contributor data converted from the AuthorshipExtractor authors-real.yml."""
    _sections = [
        "introduction",
        "the-credit-taxonomy",
        "limitations-of-current-approaches",
        "team-science-and-rising-author-lists",
        "data-model",
        "interactive-display",
        "methods",
        "discussion",
        "references",
    ]
    return ProjectContributions(
        project_name=AUTHORSHIP_REAL_PROJECT_NAME,
        sections=_sections,
        contributors=[
            AuthorContribution(
                author=Author(
                    name="Jérôme Lecoq",
                    affiliation=["Allen Institute for Neural Dynamics"],
                    email="jeromel@alleninstitute.org",
                    registry_identifier="0000-0002-0131-0938",
                ),
                credit_levels=[
                    _rc(_C, _lead),
                    _rc(_ME, _lead),
                    _rc(_SW, _lead),
                    _rc(_VA, _lead),
                    _rc(_WO, _lead),
                    _rc(_WR, _lead),
                    _rc(_VI, _lead),
                    _rc(_PA, _lead),
                    _rc(_DC, _lead),
                ],
            ),
        ],
    )
