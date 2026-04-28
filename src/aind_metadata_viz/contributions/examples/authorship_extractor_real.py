"""Real contributor data converted from AllenNeuralDynamics/AuthorshipExtractor authors-real.yml."""

from datetime import date

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


def authorship_extractor_real_contributions() -> ProjectContributions:
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
    _joined = date(2026, 3, 15)
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
                    RoleContribution(
                        role=CreditRole.CONCEPTUALIZATION,
                        level=_lead,
                        start_date=_joined,
                        description="Conceived the project and wrote the introduction",
                        linked_sections=["introduction"],
                    ),
                    RoleContribution(
                        role=CreditRole.METHODOLOGY,
                        level=_lead,
                        start_date=_joined,
                        description=(
                            "Defined and documented the multi-dimensional data model; "
                            "Designed and documented the multi-dimensional sorting approach; "
                            "Built and documented the contribution matrix"
                        ),
                        linked_sections=["data-model", "methods"],
                    ),
                    RoleContribution(
                        role=CreditRole.SOFTWARE,
                        level=_lead,
                        start_date=_joined,
                        description=(
                            "Built and documented inline contribution highlighting; "
                            "Built and documented the contribution matrix; "
                            "Built and documented the project timeline"
                        ),
                        linked_sections=["methods", "interactive-display"],
                    ),
                    RoleContribution(
                        role=CreditRole.VALIDATION,
                        level=_lead,
                        start_date=_joined,
                    ),
                    RoleContribution(
                        role=CreditRole.WRITING_ORIGINAL_DRAFT,
                        level=_lead,
                        start_date=_joined,
                        description=(
                            "Wrote the CRediT taxonomy background section; "
                            "Wrote the limitations of current approaches section; "
                            "Wrote the team science background section; "
                            "Wrote the discussion section"
                        ),
                        linked_sections=[
                            "introduction",
                            "the-credit-taxonomy",
                            "limitations-of-current-approaches",
                            "team-science-and-rising-author-lists",
                            "discussion",
                        ],
                    ),
                    RoleContribution(
                        role=CreditRole.WRITING_REVIEW_EDITING,
                        level=_lead,
                        start_date=_joined,
                    ),
                    RoleContribution(
                        role=CreditRole.VISUALIZATION,
                        level=_lead,
                        start_date=_joined,
                        description="Designed and documented the visualization architecture",
                        linked_sections=["interactive-display"],
                    ),
                    RoleContribution(
                        role=CreditRole.PROJECT_ADMINISTRATION,
                        level=_lead,
                        start_date=_joined,
                    ),
                    RoleContribution(
                        role=CreditRole.DATA_CURATION,
                        level=_lead,
                        start_date=_joined,
                        description=(
                            "Defined and documented the multi-dimensional data model; "
                            "Compiled and formatted all references"
                        ),
                        linked_sections=["data-model", "references"],
                    ),
                ],
            ),
        ],
    )
