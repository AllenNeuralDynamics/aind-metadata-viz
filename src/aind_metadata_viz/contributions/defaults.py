"""Default example: IBL 2025 paper contributor data."""

from .models import (
    Author,
    AuthorContribution,
    ContributionLevel,
    CreditRole,
    ProjectContributions,
    RoleContribution,
)

IBL_PROJECT_NAME = "ibl-2025"

_eq = ContributionLevel.EQUAL
_sp = ContributionLevel.SUPPORTING

_C = CreditRole.CONCEPTUALIZATION
_FA = CreditRole.FUNDING_ACQUISITION
_PA = CreditRole.PROJECT_ADMINISTRATION
_SUP = CreditRole.SUPERVISION
_VIZ = CreditRole.VISUALIZATION
_WOD = CreditRole.WRITING_ORIGINAL_DRAFT
_WRE = CreditRole.WRITING_REVIEW_EDITING


def _rc(role: CreditRole, level: ContributionLevel) -> RoleContribution:
    return RoleContribution(role=role, level=level)


def ibl_default_contributions() -> ProjectContributions:
    """Return the IBL 2025 paper contributor data."""
    return ProjectContributions(
        project_name=IBL_PROJECT_NAME,
        contributors=[
            AuthorContribution(
                author=Author(name="Hannah M Bayer", affiliation="Columbia University, USA"),
                credit_levels=[
                    _rc(_C, _eq),
                    _rc(_PA, _sp),
                    _rc(_SUP, _sp),
                    _rc(_WOD, _eq),
                    _rc(_WRE, _eq),
                ],
            ),
            AuthorContribution(
                author=Author(
                    name="Daniel Birman",
                    affiliation="Allen Institute, USA",
                    email="daniel.birman@alleninstitute.org",
                    registry_identifier="0000-0003-3748-6289",
                ),
                contribution_description="Contributed to conceptualization and manuscript writing.",
                credit_levels=[
                    _rc(_C, _sp),
                    _rc(_WOD, _eq),
                    _rc(_WRE, _eq),
                ],
            ),
            AuthorContribution(
                author=Author(name="Gaelle Chapuis", affiliation="University of Geneva, Switzerland"),
                credit_levels=[
                    _rc(_C, _eq),
                    _rc(_FA, _sp),
                    _rc(_PA, _eq),
                    _rc(_SUP, _sp),
                    _rc(_WOD, _eq),
                    _rc(_WRE, _eq),
                ],
            ),
            AuthorContribution(
                author=Author(name="Eric E J DeWitt", affiliation="Champalimaud Foundation, Portugal"),
                credit_levels=[
                    _rc(_WRE, _sp),
                ],
            ),
            AuthorContribution(
                author=Author(name="Laura Freitas-Silva", affiliation="Champalimaud Foundation, Portugal"),
                credit_levels=[
                    _rc(_C, _sp),
                    _rc(_FA, _sp),
                    _rc(_WRE, _sp),
                ],
            ),
            AuthorContribution(
                author=Author(name="Christopher Langdon", affiliation="Princeton University, USA"),
                credit_levels=[
                    _rc(_WRE, _sp),
                ],
            ),
            AuthorContribution(
                author=Author(name="Ines Laranjeira", affiliation="Champalimaud Foundation, Portugal"),
                credit_levels=[
                    _rc(_C, _sp),
                    _rc(_VIZ, _eq),
                    _rc(_WRE, _eq),
                ],
            ),
            AuthorContribution(
                author=Author(name="Petrina Lau", affiliation="Chinese University of Hong Kong"),
                credit_levels=[
                    _rc(_WRE, _eq),
                ],
            ),
            AuthorContribution(
                author=Author(name="Liam Paninski", affiliation="Columbia University, USA"),
                credit_levels=[
                    _rc(_PA, _eq),
                    _rc(_SUP, _sp),
                    _rc(_WOD, _sp),
                    _rc(_WRE, _eq),
                ],
            ),
            AuthorContribution(
                author=Author(name="Samuel Picard", affiliation="University College London, UK"),
                credit_levels=[
                    _rc(_VIZ, _sp),
                    _rc(_WRE, _sp),
                ],
            ),
            AuthorContribution(
                author=Author(name="Charline Tessereau", affiliation="Champalimaud Foundation, Portugal"),
                credit_levels=[
                    _rc(_C, _sp),
                    _rc(_VIZ, _eq),
                    _rc(_WRE, _eq),
                ],
            ),
            AuthorContribution(
                author=Author(name="Anne Urai", affiliation="Leiden University, The Netherlands"),
                credit_levels=[
                    _rc(_WRE, _sp),
                ],
            ),
            AuthorContribution(
                author=Author(name="Matthew R Whiteway", affiliation="Columbia University, USA"),
                credit_levels=[
                    _rc(_VIZ, _sp),
                    _rc(_WRE, _sp),
                ],
            ),
            AuthorContribution(
                author=Author(name="Olivier Winter", affiliation="Champalimaud Foundation, Portugal"),
                credit_levels=[
                    _rc(_VIZ, _sp),
                    _rc(_WRE, _sp),
                ],
            ),
        ],
    )
