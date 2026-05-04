"""Neuropixels Opto paper contributor data.

Lakunina*, Socha*, Ladd* et al. (2025)
https://doi.org/10.1101/2025.02.04.636286

Contribution matrix read from paper Fig. (CRediT table).
All contributions represented as EQUAL (★) — no H/M/L differentiation in source.
"""

from ..models import (
    Author,
    AuthorContribution,
    ContributionLevel,
    CreditRole,
    ProjectContributions,
    RoleContribution,
)

NP_OPTO_PROJECT_NAME = "np-opto"

_eq = ContributionLevel.EQUAL

_C  = CreditRole.CONCEPTUALIZATION
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

_AFF = {
    1: "Allen Institute for Neural Dynamics, Seattle, WA, USA",
    2: "UCL Institute of Ophthalmology, University College London, London, UK",
    3: "Department of Neurobiology and Biophysics, University of Washington, Seattle, WA, USA",
    4: "Janelia Research Campus, Howard Hughes Medical Institute, Ashburn, VA, USA",
    5: "Department of Biomedical Engineering, Johns Hopkins University, Baltimore, MD, USA",
    6: "IMEC, Leuven, Belgium",
    7: "Wolfson Institute for Biomedical Research, University College London, London, UK",
    8: "Allen Institute MindScope Program, Seattle, WA, USA",
    9: "Allen Institute for Brain Science, Seattle, WA, USA",
}

NP_OPTO_ASSETS = [
    "ecephys_666859_2023-06-13_14-19-34",
    "ecephys_666861_2023-05-23_10-04-20",
    "ecephys_666861_2023-05-24_14-30-05",
    "ecephys_671646_2023-07-31_15-21-40",
    "ecephys_674005_2023-08-08_15-39-38",
    "ecephys_674005_2023-08-10_13-15-14",
    "ecephys_678577_2023-11-06_15-58-49",
    "ecephys_678449_2023-08-28_17-53-41",
    "ecephys_682033_2023-10-26_14-21-51",
    "ecephys_682085_2023-10-03_16-42-49",
    "ecephys_684156_2023-10-11_17-45-08",
    "ecephys_684156_2023-10-13_16-56-59",
    "ecephys_692497_2023-12-11_16-20-55",
    "ecephys_692497_2023-12-15_16-29-04",
    "ecephys_694471_2023-12-11_14-51-57",
    "ecephys_694471_2023-12-15_15-26-01",
    "ecephys_697577_2024-02-13_16-24-10",
    "ecephys_694473_2023-11-28_15-23-23",
    "ecephys_704242_2024-04-30_17-13-29",
    "ecephys_704242_2024-05-02_16-51-50",
    "ecephys_715287_2024-04-24_15-24-43",
    "ecephys_715290_2024-05-09_15-39-23",
    "ecephys_715339_2024-05-08_16-09-35",
    "ecephys_719093_2024-05-13_16-42-41",
    "ecephys_719093_2024-05-15_15-01-10",
    "ecephys_666861_2023-05-23_10-04-20_nwb_2025-06-23_16-38-08",
    "ecephys_666861_2023-05-24_14-30-05_nwb_2025-06-23_16-41-00",
    "ecephys_671646_2023-07-31_15-21-40_nwb_2025-07-16_13-28-51",
    "ecephys_674005_2023-08-08_15-39-38_nwb_2025-06-23_22-44-21",
    "ecephys_674005_2023-08-10_13-15-14_nwb_2025-06-23_22-44-44",
    "ecephys_678449_2023-08-28_17-53-41_nwb_2025-07-14_16-17-23",
    "ecephys_678577_2023-11-06_15-58-49_nwb_2025-06-23_17-17-53",
    "ecephys_682033_2023-10-26_14-21-51_nwb_2025-07-14_16-33-11",
    "ecephys_682085_2023-10-03_16-42-49_nwb_2025-07-15_08-51-19",
    "ecephys_684156_2023-10-11_17-45-08_nwb_2025-07-14_16-40-07",
    "ecephys_684156_2023-10-13_16-56-59_nwb_2025-07-14_16-42-11",
    "ecephys_692497_2023-12-11_16-20-55_nwb_2025-07-14_17-04-29",
    "ecephys_692497_2023-12-15_16-29-04_nwb_2025-07-14_17-07-23",
    "ecephys_694471_2023-12-11_14-51-57_nwb_2025-06-23_22-29-32",
    "ecephys_694471_2023-12-15_15-26-01_nwb_2025-06-23_22-31-12",
    "ecephys_694473_2023-11-28_15-23-23_nwb_2025-07-16_15-35-44",
    "ecephys_697577_2024-02-13_16-24-10_nwb_2025-07-16_15-14-08",
    "ecephys_704242_2024-04-30_17-13-29_nwb_2025-07-14_17-16-50",
    "ecephys_704242_2024-05-02_16-51-50_nwb_2025-07-14_17-19-21",
    "ecephys_715287_2024-04-24_15-24-43_nwb_2025-07-15_11-24-09",
    "ecephys_715290_2024-05-09_15-39-23_nwb_2025-07-16_15-23-53",
    "ecephys_715339_2024-05-08_16-09-35_nwb_2025-07-16_15-27-40",
    "ecephys_719093_2024-05-15_15-01-10_nwb_2025-07-16_15-48-15",
    "ecephys_719093_2024-05-13_16-42-41_nwb_2025-07-16_15-50-08",
    "ecephys_655571_2023-05-09_13-53-48_nwb_2025-06-23_15-59-17",
]


def _rc(role: CreditRole, level: ContributionLevel = _eq) -> RoleContribution:
    return RoleContribution(role=role, level=level)


def np_opto_contributions() -> ProjectContributions:
    """Return Neuropixels Opto paper contributor data."""
    return ProjectContributions(
        project_name=NP_OPTO_PROJECT_NAME,
        doi="https://doi.org/10.1101/2025.02.04.636286",
        assets=NP_OPTO_ASSETS,
        contributors=[
            # Anna Lakunina — equal first author (*)
            AuthorContribution(
                author=Author(
                    name="Anna Lakunina",
                    affiliation=[_AFF[1]],
                ),
                credit_levels=[
                    _rc(_DC), _rc(_IN),
                ],
            ),
            # Karolina Z Socha — equal first author (*)
            AuthorContribution(
                author=Author(
                    name="Karolina Z Socha",
                    affiliation=[_AFF[2]],
                ),
                credit_levels=[
                    _rc(_DC), _rc(_FA), _rc(_IN), _rc(_VA), _rc(_VI),
                    _rc(_WO), _rc(_WR),
                ],
            ),
            # Alexander Ladd — equal first author (*)
            AuthorContribution(
                author=Author(
                    name="Alexander Ladd",
                    affiliation=[_AFF[3]],
                ),
                credit_levels=[
                    _rc(_DC), _rc(_FA), _rc(_IN), _rc(_VI), _rc(_WO), _rc(_WR),
                ],
            ),
            # Anna J Bowen
            AuthorContribution(
                author=Author(
                    name="Anna J Bowen",
                    affiliation=[_AFF[3]],
                ),
                credit_levels=[
                    _rc(_IN),
                ],
            ),
            # Susu Chen
            AuthorContribution(
                author=Author(
                    name="Susu Chen",
                    affiliation=[_AFF[4]],
                ),
                credit_levels=[
                    _rc(_IN), _rc(_VA),
                ],
            ),
            # Jennifer Colonell
            AuthorContribution(
                author=Author(
                    name="Jennifer Colonell",
                    affiliation=[_AFF[4], _AFF[5]],
                ),
                credit_levels=[
                    _rc(_SW),
                ],
            ),
            # Anjal Doshi
            AuthorContribution(
                author=Author(
                    name="Anjal Doshi",
                    affiliation=[_AFF[1]],
                ),
                credit_levels=[
                    _rc(_C), _rc(_ME), _rc(_PA),
                ],
            ),
            # Bill Karsh
            AuthorContribution(
                author=Author(
                    name="Bill Karsh",
                    affiliation=[_AFF[4], _AFF[5]],
                ),
                credit_levels=[
                    _rc(_SW), _rc(_VA),
                ],
            ),
            # Michael Krumin
            AuthorContribution(
                author=Author(
                    name="Michael Krumin",
                    affiliation=[_AFF[2]],
                ),
                credit_levels=[
                    _rc(_SW),
                ],
            ),
            # Pavel Kulik
            AuthorContribution(
                author=Author(
                    name="Pavel Kulik",
                    affiliation=[_AFF[1]],
                ),
                credit_levels=[
                    _rc(_DC), _rc(_FA), _rc(_SW), _rc(_VI), _rc(_WR),
                ],
            ),
            # Anna Li
            AuthorContribution(
                author=Author(
                    name="Anna Li",
                    affiliation=[_AFF[3]],
                ),
                credit_levels=[
                    _rc(_IN), _rc(_WR),
                ],
            ),
            # Pieter Neutens
            AuthorContribution(
                author=Author(
                    name="Pieter Neutens",
                    affiliation=[_AFF[6]],
                ),
                credit_levels=[
                    _rc(_IN), _rc(_ME),
                ],
            ),
            # John O'Callaghan
            AuthorContribution(
                author=Author(
                    name="John O'Callaghan",
                    affiliation=[_AFF[6]],
                ),
                credit_levels=[
                    _rc(_IN), _rc(_ME),
                ],
            ),
            # Meghan Olsen
            AuthorContribution(
                author=Author(
                    name="Meghan Olsen",
                    affiliation=[_AFF[1]],
                ),
                credit_levels=[
                    _rc(_IN),
                ],
            ),
            # Jan Putzeys
            AuthorContribution(
                author=Author(
                    name="Jan Putzeys",
                    affiliation=[_AFF[6]],
                ),
                credit_levels=[
                    _rc(_ME),
                ],
            ),
            # Harrie AC Tilmans
            AuthorContribution(
                author=Author(
                    name="Harrie AC Tilmans",
                    affiliation=[_AFF[6]],
                ),
                credit_levels=[
                    _rc(_RE),
                ],
            ),
            # Zhiwen Ye
            AuthorContribution(
                author=Author(
                    name="Zhiwen Ye",
                    affiliation=[_AFF[3]],
                ),
                credit_levels=[
                    _rc(_IN),
                ],
            ),
            # Marleen Welkenhuysen
            AuthorContribution(
                author=Author(
                    name="Marleen Welkenhuysen",
                    affiliation=[_AFF[6]],
                ),
                credit_levels=[
                    _rc(_ME),
                ],
            ),
            # Michael Häusser
            AuthorContribution(
                author=Author(
                    name="Michael Häusser",
                    affiliation=[_AFF[7]],
                ),
                credit_levels=[
                    _rc(_FN), _rc(_SU),
                ],
            ),
            # Christof Koch
            AuthorContribution(
                author=Author(
                    name="Christof Koch",
                    affiliation=[_AFF[8]],
                ),
                credit_levels=[
                    _rc(_FA), _rc(_FN), _rc(_SU),
                ],
            ),
            # Jonathan T. Ting
            AuthorContribution(
                author=Author(
                    name="Jonathan T. Ting",
                    affiliation=[_AFF[3], _AFF[9]],
                ),
                credit_levels=[
                    _rc(_IN),
                ],
            ),
            # Barun Dutta
            AuthorContribution(
                author=Author(
                    name="Barun Dutta",
                    affiliation=[_AFF[6]],
                ),
                credit_levels=[
                    _rc(_RE), _rc(_SU),
                ],
            ),
            # Timothy D Harris
            AuthorContribution(
                author=Author(
                    name="Timothy D Harris",
                    affiliation=[_AFF[4], _AFF[5]],
                ),
                credit_levels=[
                    _rc(_FN), _rc(_RE), _rc(_SU),
                ],
            ),
            # Nicholas A Steinmetz
            AuthorContribution(
                author=Author(
                    name="Nicholas A Steinmetz",
                    affiliation=[_AFF[3]],
                ),
                credit_levels=[
                    _rc(_C), _rc(_FN), _rc(_ME), _rc(_RE), _rc(_SU),
                    _rc(_WO), _rc(_WR),
                ],
            ),
            # Karel Svoboda — co-senior author (†)
            AuthorContribution(
                author=Author(
                    name="Karel Svoboda",
                    affiliation=[_AFF[1], _AFF[4]],
                ),
                credit_levels=[
                    _rc(_C), _rc(_FN), _rc(_ME), _rc(_RE), _rc(_SU), _rc(_WR),
                ],
            ),
            # Joshua H Siegle — co-senior author (†)
            AuthorContribution(
                author=Author(
                    name="Joshua H Siegle",
                    affiliation=[_AFF[1]],
                ),
                credit_levels=[
                    _rc(_C), _rc(_FA), _rc(_FN), _rc(_PA), _rc(_RE), _rc(_SW),
                    _rc(_SU), _rc(_VI), _rc(_WO), _rc(_WR),
                ],
            ),
            # Matteo Carandini — co-senior author (†)
            AuthorContribution(
                author=Author(
                    name="Matteo Carandini",
                    affiliation=[_AFF[2]],
                ),
                credit_levels=[
                    _rc(_C), _rc(_FN), _rc(_PA), _rc(_RE), _rc(_SU), _rc(_VI),
                    _rc(_WO), _rc(_WR),
                ],
            ),
        ],
    )
