"""50-author neuroscience consortium converted from AllenNeuralDynamics/AuthorshipExtractor authors-large.yml."""

from ..models import (
    Author,
    AuthorContribution,
    ContributionLevel,
    CreditRole,
    ProjectContributions,
    RoleContribution,
)

AUTHORSHIP_LARGE_PROJECT_NAME = "authorship-extractor-large"

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


_AFFILIATIONS = {
    "ucl-neuro": "UCL Queen Square Institute of Neurology, University College London",
    "utokyo-neuro": "Department of Neurophysiology, University of Tokyo",
    "unam-neuro": "Institute of Neurobiology, National Autonomous University of Mexico",
    "karolinska-neuro": "Department of Neuroscience, Karolinska Institute",
    "aiims-neuro": "Department of Neurology, All India Institute of Medical Sciences",
    "mit-neuro": "Department of Brain and Cognitive Sciences, Massachusetts Institute of Technology",
    "mpibr": "Department of Connectomics, Max Planck Institute for Brain Research",
    "ethz-neuro": "Institute of Neuroinformatics, ETH Zurich",
    "uct-neuro": "Division of Neuroscience, University of Cape Town",
    "snu-neuro": "Department of Brain and Cognitive Sciences, Seoul National University",
    "usp-neuro": "Department of Neuroscience and Behavior, University of São Paulo",
}


def authorship_extractor_large_contributions() -> ProjectContributions:
    """Return contributor data converted from the AuthorshipExtractor authors-large.yml."""
    _sections = [
        "introduction",
        "the-credit-taxonomy",
        "limitations-of-current-approaches",
        "team-science-and-rising-author-lists",
        "data-model",
        "interactive-display",
        "methods",
        "discussion",
    ]
    return ProjectContributions(
        project_name=AUTHORSHIP_LARGE_PROJECT_NAME,
        sections=_sections,
        contributors=[
            # 1
            AuthorContribution(
                author=Author(
                    name="Amara Osei-Mensah",
                    affiliation=[_AFFILIATIONS["ucl-neuro"]],
                    email="a.osei-mensah@ucl.ac.uk",
                    registry_identifier="0000-0002-1100-2200",
                ),
                credit_levels=[
                    _rc(_C, _lead), _rc(_SU, _lead), _rc(_FN, _lead),
                    _rc(_PA, _lead), _rc(_WR, _lead), _rc(_ME, _eq),
                ],
            ),
            # 2
            AuthorContribution(
                author=Author(
                    name="Hiroshi Tanaka",
                    affiliation=[_AFFILIATIONS["utokyo-neuro"]],
                    registry_identifier="0000-0001-3300-4400",
                ),
                credit_levels=[
                    _rc(_C, _eq), _rc(_SU, _lead), _rc(_FN, _eq),
                    _rc(_WR, _eq), _rc(_ME, _lead),
                ],
            ),
            # 3
            AuthorContribution(
                author=Author(
                    name="Elena Vasquez-Moreno",
                    affiliation=[_AFFILIATIONS["unam-neuro"]],
                    email="evasquez@ifc.unam.mx",
                    registry_identifier="0000-0003-5500-6600",
                ),
                credit_levels=[
                    _rc(_C, _eq), _rc(_SU, _eq), _rc(_FN, _eq),
                    _rc(_WR, _eq), _rc(_WO, _eq),
                ],
            ),
            # 4
            AuthorContribution(
                author=Author(
                    name="Lars Eriksson",
                    affiliation=[_AFFILIATIONS["karolinska-neuro"]],
                    registry_identifier="0000-0002-7700-8800",
                ),
                credit_levels=[
                    _rc(_ME, _lead), _rc(_FA, _eq), _rc(_WO, _eq), _rc(_SU, _sp),
                ],
            ),
            # 5
            AuthorContribution(
                author=Author(
                    name="Priya Chakraborty",
                    affiliation=[_AFFILIATIONS["aiims-neuro"]],
                    registry_identifier="0000-0001-9900-1011",
                ),
                credit_levels=[
                    _rc(_C, _sp), _rc(_ME, _eq), _rc(_IN, _lead), _rc(_WR, _eq),
                ],
            ),
            # 6
            AuthorContribution(
                author=Author(
                    name="James Whitfield",
                    affiliation=[_AFFILIATIONS["mit-neuro"]],
                    registry_identifier="0000-0003-1122-3344",
                ),
                credit_levels=[
                    _rc(_ME, _eq), _rc(_FA, _lead), _rc(_SW, _sp),
                    _rc(_WO, _eq), _rc(_SU, _eq),
                ],
            ),
            # 7
            AuthorContribution(
                author=Author(
                    name="Fatima Al-Rashidi",
                    affiliation=[_AFFILIATIONS["mpibr"]],
                    registry_identifier="0000-0002-4455-6677",
                ),
                credit_levels=[
                    _rc(_IN, _lead), _rc(_ME, _eq), _rc(_WO, _eq), _rc(_FA, _eq),
                ],
            ),
            # 8
            AuthorContribution(
                author=Author(
                    name="Wei Zhang",
                    affiliation=[_AFFILIATIONS["ethz-neuro"]],
                    registry_identifier="0000-0001-5566-7788",
                ),
                credit_levels=[
                    _rc(_ME, _eq), _rc(_SW, _eq), _rc(_FA, _eq),
                    _rc(_VI, _lead), _rc(_WR, _sp),
                ],
            ),
            # 9
            AuthorContribution(
                author=Author(
                    name="Kofi Asante",
                    affiliation=[_AFFILIATIONS["ucl-neuro"]],
                    registry_identifier="0000-0003-6677-8899",
                ),
                credit_levels=[
                    _rc(_IN, _eq), _rc(_ME, _eq), _rc(_WO, _eq), _rc(_FA, _eq),
                ],
            ),
            # 10
            AuthorContribution(
                author=Author(
                    name="Yuki Morimoto",
                    affiliation=[_AFFILIATIONS["utokyo-neuro"]],
                    registry_identifier="0000-0002-7788-9900",
                ),
                credit_levels=[
                    _rc(_SW, _eq), _rc(_VA, _lead), _rc(_WO, _eq), _rc(_ME, _sp),
                ],
            ),
            # 11
            AuthorContribution(
                author=Author(
                    name="Maria da Silva Gonzalez",
                    affiliation=[_AFFILIATIONS["usp-neuro"]],
                    registry_identifier="0000-0001-8899-0011",
                ),
                credit_levels=[
                    _rc(_IN, _lead), _rc(_WO, _eq), _rc(_FA, _eq), _rc(_VI, _sp),
                ],
            ),
            # 12
            AuthorContribution(
                author=Author(
                    name="Oluwaseun Adeyemi",
                    affiliation=[_AFFILIATIONS["uct-neuro"]],
                    registry_identifier="0000-0003-9900-1122",
                ),
                credit_levels=[
                    _rc(_SW, _lead), _rc(_ME, _eq), _rc(_VA, _eq), _rc(_WO, _eq),
                ],
            ),
            # 13
            AuthorContribution(
                author=Author(
                    name="Sanjay Krishnamurthy",
                    affiliation=[_AFFILIATIONS["mit-neuro"]],
                    registry_identifier="0000-0001-0011-2233",
                ),
                credit_levels=[
                    _rc(_FA, _lead), _rc(_ME, _eq), _rc(_SW, _eq), _rc(_VA, _eq),
                ],
            ),
            # 14
            AuthorContribution(
                author=Author(
                    name="Anastasia Volkov",
                    affiliation=[_AFFILIATIONS["mpibr"]],
                    registry_identifier="0000-0002-1122-3344",
                ),
                credit_levels=[
                    _rc(_IN, _eq), _rc(_DC, _lead), _rc(_WO, _eq), _rc(_WR, _eq),
                ],
            ),
            # 15
            AuthorContribution(
                author=Author(
                    name="Chen Wei-Lin",
                    affiliation=[_AFFILIATIONS["ethz-neuro"]],
                    registry_identifier="0000-0003-2233-4455",
                ),
                credit_levels=[
                    _rc(_SW, _lead), _rc(_VI, _eq), _rc(_VA, _eq), _rc(_FA, _sp),
                ],
            ),
            # 16
            AuthorContribution(
                author=Author(
                    name="Tomoko Hashimoto",
                    affiliation=[_AFFILIATIONS["utokyo-neuro"]],
                    registry_identifier="0000-0001-3344-5566",
                ),
                credit_levels=[
                    _rc(_IN, _eq), _rc(_DC, _eq), _rc(_WO, _eq), _rc(_ME, _sp),
                ],
            ),
            # 17
            AuthorContribution(
                author=Author(
                    name="Rodrigo Ferreira",
                    affiliation=[_AFFILIATIONS["usp-neuro"]],
                    registry_identifier="0000-0002-4455-6677",
                ),
                credit_levels=[
                    _rc(_SW, _eq), _rc(_VI, _lead), _rc(_FA, _sp), _rc(_WO, _sp),
                ],
            ),
            # 18
            AuthorContribution(
                author=Author(
                    name="Nadia El-Amin",
                    affiliation=[_AFFILIATIONS["karolinska-neuro"]],
                    registry_identifier="0000-0003-5566-7788",
                ),
                credit_levels=[
                    _rc(_ME, _eq), _rc(_FA, _eq), _rc(_WO, _eq), _rc(_IN, _sp),
                ],
            ),
            # 19
            AuthorContribution(
                author=Author(
                    name="Hyunjin Park",
                    affiliation=[_AFFILIATIONS["snu-neuro"]],
                    registry_identifier="0000-0001-6677-8899",
                ),
                credit_levels=[
                    _rc(_SW, _eq), _rc(_VA, _eq), _rc(_IN, _sp),
                ],
            ),
            # 20
            AuthorContribution(
                author=Author(
                    name="Adesola Ogunlade",
                    affiliation=[_AFFILIATIONS["ucl-neuro"]],
                    registry_identifier="0000-0002-7788-9900",
                ),
                credit_levels=[
                    _rc(_IN, _eq), _rc(_WO, _eq), _rc(_FA, _sp),
                ],
            ),
            # 21
            AuthorContribution(
                author=Author(
                    name="Luisa Moretti",
                    affiliation=[_AFFILIATIONS["ethz-neuro"]],
                    registry_identifier="0000-0003-8899-0011",
                ),
                credit_levels=[
                    _rc(_SW, _eq), _rc(_VI, _eq), _rc(_VA, _eq), _rc(_FA, _sp),
                ],
            ),
            # 22
            AuthorContribution(
                author=Author(
                    name="Ravi Sharma",
                    affiliation=[_AFFILIATIONS["aiims-neuro"]],
                    registry_identifier="0000-0001-9900-1122",
                ),
                credit_levels=[
                    _rc(_IN, _eq), _rc(_ME, _sp), _rc(_WO, _eq),
                ],
            ),
            # 23
            AuthorContribution(
                author=Author(
                    name="Ekaterina Sokolova",
                    affiliation=[_AFFILIATIONS["mpibr"]],
                    registry_identifier="0000-0002-0011-2233",
                ),
                credit_levels=[
                    _rc(_FA, _eq), _rc(_SW, _eq), _rc(_VA, _eq), _rc(_IN, _sp),
                ],
            ),
            # 24
            AuthorContribution(
                author=Author(
                    name="Diego Ramirez",
                    affiliation=[_AFFILIATIONS["unam-neuro"]],
                    registry_identifier="0000-0003-1122-3344",
                ),
                credit_levels=[
                    _rc(_SW, _lead), _rc(_VI, _eq), _rc(_IN, _sp),
                ],
            ),
            # 25
            AuthorContribution(
                author=Author(
                    name="Mei Huang",
                    affiliation=[_AFFILIATIONS["mit-neuro"]],
                    registry_identifier="0000-0001-2233-4455",
                ),
                credit_levels=[
                    _rc(_FA, _eq), _rc(_SW, _eq), _rc(_VA, _lead), _rc(_WO, _sp),
                ],
            ),
            # 26
            AuthorContribution(
                author=Author(
                    name="Benjamin Nkrumah",
                    affiliation=[_AFFILIATIONS["uct-neuro"]],
                    registry_identifier="0000-0002-3344-5566",
                ),
                credit_levels=[
                    _rc(_IN, _eq), _rc(_DC, _eq), _rc(_WO, _sp),
                ],
            ),
            # 27
            AuthorContribution(
                author=Author(
                    name="Aiko Watanabe",
                    affiliation=[_AFFILIATIONS["utokyo-neuro"]],
                    registry_identifier="0000-0003-4455-6677",
                ),
                credit_levels=[
                    _rc(_SW, _eq), _rc(_VI, _eq), _rc(_VA, _sp),
                ],
            ),
            # 28
            AuthorContribution(
                author=Author(
                    name="Thiago Costa",
                    affiliation=[_AFFILIATIONS["usp-neuro"]],
                    registry_identifier="0000-0001-5566-7788",
                ),
                credit_levels=[
                    _rc(_IN, _eq), _rc(_FA, _sp), _rc(_WO, _sp),
                ],
            ),
            # 29
            AuthorContribution(
                author=Author(
                    name="Sarah O'Brien",
                    affiliation=[_AFFILIATIONS["ucl-neuro"]],
                    registry_identifier="0000-0002-6677-8899",
                ),
                credit_levels=[
                    _rc(_ME, _sp), _rc(_IN, _eq), _rc(_WO, _eq), _rc(_DC, _eq),
                ],
            ),
            # 30
            AuthorContribution(
                author=Author(
                    name="Kenji Yamamoto",
                    affiliation=[_AFFILIATIONS["karolinska-neuro"]],
                    registry_identifier="0000-0003-7788-9900",
                ),
                credit_levels=[
                    _rc(_SW, _eq), _rc(_FA, _sp), _rc(_VA, _eq),
                ],
            ),
            # 31
            AuthorContribution(
                author=Author(
                    name="Deepa Venkatesh",
                    affiliation=[_AFFILIATIONS["aiims-neuro"]],
                    registry_identifier="0000-0001-8899-0011",
                ),
                credit_levels=[
                    _rc(_IN, _eq), _rc(_DC, _lead), _rc(_WO, _eq),
                ],
            ),
            # 32
            AuthorContribution(
                author=Author(
                    name="Ahmed Hassan",
                    affiliation=[_AFFILIATIONS["mpibr"]],
                    registry_identifier="0000-0002-9900-1122",
                ),
                credit_levels=[
                    _rc(_SW, _eq), _rc(_VI, _eq), _rc(_FA, _sp),
                ],
            ),
            # 33
            AuthorContribution(
                author=Author(
                    name="Ji-Yeon Choi",
                    affiliation=[_AFFILIATIONS["snu-neuro"]],
                    registry_identifier="0000-0003-0011-2233",
                ),
                credit_levels=[
                    _rc(_IN, _eq), _rc(_FA, _eq), _rc(_WO, _sp), _rc(_ME, _sp),
                ],
            ),
            # 34
            AuthorContribution(
                author=Author(
                    name="Marcus Jensen",
                    affiliation=[_AFFILIATIONS["mit-neuro"]],
                    registry_identifier="0000-0001-1122-3344",
                ),
                credit_levels=[
                    _rc(_SW, _lead), _rc(_RE, _lead), _rc(_VA, _eq),
                ],
            ),
            # 35
            AuthorContribution(
                author=Author(
                    name="Yuto Nakagawa",
                    affiliation=[_AFFILIATIONS["utokyo-neuro"]],
                    registry_identifier="0000-0002-2233-4455",
                ),
                credit_levels=[
                    _rc(_SW, _eq), _rc(_RE, _eq), _rc(_DC, _eq), _rc(_VA, _sp),
                ],
            ),
            # 36
            AuthorContribution(
                author=Author(
                    name="Olga Petersen",
                    affiliation=[_AFFILIATIONS["mpibr"]],
                    registry_identifier="0000-0003-3344-5566",
                ),
                credit_levels=[
                    _rc(_FA, _eq), _rc(_ME, _eq), _rc(_IN, _eq), _rc(_VA, _lead),
                ],
            ),
            # 37
            AuthorContribution(
                author=Author(
                    name="Tariq Mansoor",
                    affiliation=[_AFFILIATIONS["ucl-neuro"]],
                    registry_identifier="0000-0001-4455-6677",
                ),
                credit_levels=[
                    _rc(_SW, _eq), _rc(_RE, _eq), _rc(_VA, _eq),
                ],
            ),
            # 38
            AuthorContribution(
                author=Author(
                    name="Camila Reyes",
                    affiliation=[_AFFILIATIONS["usp-neuro"]],
                    registry_identifier="0000-0002-5566-7788",
                ),
                credit_levels=[
                    _rc(_IN, _eq), _rc(_FA, _eq), _rc(_WO, _sp), _rc(_DC, _eq),
                ],
            ),
            # 39
            AuthorContribution(
                author=Author(
                    name="David Chang",
                    affiliation=[_AFFILIATIONS["mit-neuro"]],
                    registry_identifier="0000-0003-6677-8899",
                ),
                credit_levels=[
                    _rc(_SW, _lead), _rc(_RE, _eq), _rc(_VI, _eq),
                ],
            ),
            # 40
            AuthorContribution(
                author=Author(
                    name="Nneka Igwe",
                    affiliation=[_AFFILIATIONS["uct-neuro"]],
                    registry_identifier="0000-0001-7788-9900",
                ),
                credit_levels=[
                    _rc(_IN, _eq), _rc(_ME, _eq), _rc(_FA, _eq), _rc(_WO, _sp),
                ],
            ),
            # 41
            AuthorContribution(
                author=Author(
                    name="Sofia Lindqvist",
                    affiliation=[_AFFILIATIONS["karolinska-neuro"]],
                    registry_identifier="0000-0002-8899-0011",
                ),
                credit_levels=[
                    _rc(_SW, _eq), _rc(_VI, _lead), _rc(_RE, _sp), _rc(_VA, _eq),
                ],
            ),
            # 42
            AuthorContribution(
                author=Author(
                    name="Hannah Becker",
                    affiliation=[_AFFILIATIONS["mpibr"]],
                    registry_identifier="0000-0003-9900-1122",
                ),
                credit_levels=[
                    _rc(_DC, _lead), _rc(_RE, _eq), _rc(_VA, _sp),
                ],
            ),
            # 43
            AuthorContribution(
                author=Author(
                    name="Raj Patel",
                    affiliation=[_AFFILIATIONS["aiims-neuro"]],
                    registry_identifier="0000-0001-0011-2233",
                ),
                credit_levels=[
                    _rc(_RE, _lead), _rc(_PA, _eq), _rc(_DC, _sp),
                ],
            ),
            # 44
            AuthorContribution(
                author=Author(
                    name="Mitsuki Endo",
                    affiliation=[_AFFILIATIONS["utokyo-neuro"]],
                    registry_identifier="0000-0002-1122-3344",
                ),
                credit_levels=[
                    _rc(_PA, _eq), _rc(_RE, _eq), _rc(_DC, _eq),
                ],
            ),
            # 45
            AuthorContribution(
                author=Author(
                    name="Grace Mensah",
                    affiliation=[_AFFILIATIONS["uct-neuro"]],
                    registry_identifier="0000-0003-2233-4456",
                ),
                credit_levels=[
                    _rc(_DC, _lead), _rc(_VA, _eq), _rc(_RE, _sp),
                ],
            ),
            # 46
            AuthorContribution(
                author=Author(
                    name="Carlos Rivera",
                    affiliation=[_AFFILIATIONS["unam-neuro"]],
                    registry_identifier="0000-0001-3344-5567",
                ),
                credit_levels=[
                    _rc(_RE, _lead), _rc(_PA, _eq), _rc(_DC, _sp),
                ],
            ),
            # 47
            AuthorContribution(
                author=Author(
                    name="Emma Thompson",
                    affiliation=[_AFFILIATIONS["ucl-neuro"]],
                    registry_identifier="0000-0002-4455-6678",
                ),
                credit_levels=[
                    _rc(_IN, _sp), _rc(_DC, _sp),
                ],
            ),
            # 48
            AuthorContribution(
                author=Author(
                    name="Takeshi Mori",
                    affiliation=[_AFFILIATIONS["utokyo-neuro"]],
                    registry_identifier="0000-0003-5566-7789",
                ),
                credit_levels=[
                    _rc(_SW, _sp), _rc(_VI, _sp),
                ],
            ),
            # 49
            AuthorContribution(
                author=Author(
                    name="Zara Khan",
                    affiliation=[_AFFILIATIONS["mit-neuro"]],
                    registry_identifier="0000-0001-6677-8890",
                ),
                credit_levels=[
                    _rc(_IN, _sp), _rc(_DC, _sp),
                ],
            ),
            # 50
            AuthorContribution(
                author=Author(
                    name="Lucas Almeida",
                    affiliation=[_AFFILIATIONS["usp-neuro"]],
                    registry_identifier="0000-0002-7788-9901",
                ),
                credit_levels=[
                    _rc(_IN, _sp), _rc(_VI, _sp),
                ],
            ),
        ],
    )
