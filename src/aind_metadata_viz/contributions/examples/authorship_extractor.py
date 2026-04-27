"""AuthorshipExtractor example: converted from AllenNeuralDynamics/AuthorshipExtractor authors.yml."""

from ..models import (
    Author,
    AuthorContribution,
    ContributionLevel,
    CreditRole,
    ProjectContributions,
    RoleContribution,
)

AUTHORSHIP_PROJECT_NAME = "authorship-extractor-simulated"

_lead = ContributionLevel.LEAD
_sp = ContributionLevel.SUPPORTING
_eq = ContributionLevel.EQUAL

_C = CreditRole.CONCEPTUALIZATION
_DC = CreditRole.DATA_CURATION
_FA = CreditRole.FORMAL_ANALYSIS
_FN = CreditRole.FUNDING_ACQUISITION
_IN = CreditRole.INVESTIGATION
_ME = CreditRole.METHODOLOGY
_PA = CreditRole.PROJECT_ADMINISTRATION
_RE = CreditRole.RESOURCES
_SW = CreditRole.SOFTWARE
_SU = CreditRole.SUPERVISION
_VA = CreditRole.VALIDATION
_VI = CreditRole.VISUALIZATION
_WO = CreditRole.WRITING_ORIGINAL_DRAFT
_WR = CreditRole.WRITING_REVIEW_EDITING


def _rc(role: CreditRole, level: ContributionLevel) -> RoleContribution:
    return RoleContribution(role=role, level=level)


# Resolved from the affiliations block in authors.yml
_AFFILIATIONS = {
    "stanford-comm": "Department of Communication, Stanford University",
    "cos": "Center for Open Science",
    "stanford-cs": "Department of Computer Science, Stanford University",
    "stanford-dschool": "d.school (Hasso Plattner Institute of Design), Stanford University",
    "stanford-lib": "Stanford Libraries / Research Data Services, Stanford University",
    "stanford-hci": "Human-Computer Interaction Group, Stanford University",
    "columbia-is": "Department of Information Science, Columbia University",
    "rori": "Research on Research Institute",
}


def authorship_extractor_contributions() -> ProjectContributions:
    """Return contributor data converted from the AuthorshipExtractor authors.yml."""
    _sections = [
        "introduction",
        "the-credit-taxonomy",
        "data-model",
        "methods",
        "interactive-display",
        "limitations-of-current-approaches",
        "team-science-and-rising-author-lists",
        "discussion",
    ]
    return ProjectContributions(
        project_name=AUTHORSHIP_PROJECT_NAME,
        sections=_sections,
        contributors=[
            AuthorContribution(
                author=Author(
                    name="Mei-Lin Chen",
                    affiliation=[
                        _AFFILIATIONS["stanford-comm"],
                        _AFFILIATIONS["cos"],
                    ],
                    email="mchen@stanford.edu",
                    registry_identifier="0000-0002-1234-5678",
                ),
                credit_levels=[
                    _rc(_C, _lead),
                    _rc(_SU, _lead),
                    _rc(_FN, _lead),
                    _rc(_PA, _lead),
                    _rc(_WR, _lead),
                    _rc(_ME, _eq),
                    _rc(_WO, _sp),
                ],
            ),
            AuthorContribution(
                author=Author(
                    name="Chukwuemeka Okafor",
                    affiliation=[_AFFILIATIONS["stanford-cs"]],
                    registry_identifier="0000-0003-2345-6789",
                ),
                credit_levels=[
                    _rc(_IN, _lead),
                    _rc(_ME, _lead),
                    _rc(_WO, _lead),
                    _rc(_FA, _eq),
                    _rc(_DC, _lead),
                    _rc(_VA, _eq),
                    _rc(_VI, _eq),
                ],
            ),
            AuthorContribution(
                author=Author(
                    name="Yuki Nakamura",
                    affiliation=[_AFFILIATIONS["stanford-cs"]],
                    registry_identifier="0000-0001-3456-7890",
                ),
                credit_levels=[
                    _rc(_SW, _lead),
                    _rc(_FA, _lead),
                    _rc(_ME, _eq),
                    _rc(_WO, _eq),
                    _rc(_VI, _eq),
                    _rc(_VA, _lead),
                ],
            ),
            AuthorContribution(
                author=Author(
                    name="Isabella Santos-Rivera",
                    affiliation=[_AFFILIATIONS["stanford-dschool"]],
                    registry_identifier="0000-0002-4567-8901",
                ),
                credit_levels=[
                    _rc(_IN, _eq),
                    _rc(_ME, _sp),
                    _rc(_RE, _lead),
                    _rc(_WR, _sp),
                ],
            ),
            AuthorContribution(
                author=Author(
                    name="Jihoon Kim",
                    affiliation=[_AFFILIATIONS["stanford-lib"]],
                    registry_identifier="0000-0003-5678-9012",
                ),
                credit_levels=[
                    _rc(_SW, _eq),
                    _rc(_DC, _lead),
                    _rc(_RE, _eq),
                    _rc(_VA, _sp),
                ],
            ),
            AuthorContribution(
                author=Author(
                    name="Alexei Petrov",
                    affiliation=[_AFFILIATIONS["stanford-hci"]],
                    registry_identifier="0000-0001-6789-0123",
                ),
                credit_levels=[
                    _rc(_RE, _lead),
                    _rc(_ME, _sp),
                    _rc(_SW, _sp),
                ],
            ),
            AuthorContribution(
                author=Author(
                    name="Diane Williams",
                    affiliation=[
                        _AFFILIATIONS["columbia-is"],
                        _AFFILIATIONS["rori"],
                    ],
                    registry_identifier="0000-0002-7890-1234",
                ),
                credit_levels=[
                    _rc(_C, _sp),
                    _rc(_ME, _sp),
                    _rc(_WR, _eq),
                    _rc(_SU, _sp),
                    _rc(_FN, _sp),
                ],
            ),
        ],
    )
