"""IBL decision-making paper contributor data.

Contribution levels from the paper's author contribution statement:
H (high) → lead, M (medium) / L (low) → supporting
"""

from ..models import (
    Author,
    AuthorContribution,
    ContributionLevel,
    CreditRole,
    ProjectContributions,
    RoleContribution,
)

IBL_DECISION_PROJECT_NAME = "ibl-decision-making"

_lead = ContributionLevel.LEAD
_sp = ContributionLevel.SUPPORTING

_C = CreditRole.CONCEPTUALIZATION
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


def ibl_decision_contributions() -> ProjectContributions:
    """Return IBL decision-making paper contributor data."""
    return ProjectContributions(
        project_name=IBL_DECISION_PROJECT_NAME,
        contributors=[
            # Charles Findling
            AuthorContribution(
                author=Author(name="Charles Findling"),
                credit_levels=[
                    _rc(_C, _lead), _rc(_FA, _lead), _rc(_ME, _lead),
                    _rc(_PA, _lead), _rc(_RE, _lead), _rc(_SW, _lead),
                    _rc(_SU, _lead), _rc(_VA, _lead), _rc(_VI, _lead),
                    _rc(_WO, _lead), _rc(_WR, _lead),
                ],
            ),
            # Félix Hubert
            AuthorContribution(
                author=Author(name="Félix Hubert"),
                credit_levels=[
                    _rc(_C, _lead), _rc(_FA, _lead), _rc(_ME, _lead),
                    _rc(_SW, _lead), _rc(_VA, _lead), _rc(_VI, _lead),
                    _rc(_WO, _lead), _rc(_WR, _sp),
                ],
            ),
            # Luigi Acerbi
            AuthorContribution(
                author=Author(name="Luigi Acerbi"),
                credit_levels=[
                    _rc(_ME, _sp), _rc(_WR, _sp),
                ],
            ),
            # Brandon Benson
            AuthorContribution(
                author=Author(name="Brandon Benson"),
                credit_levels=[
                    _rc(_FA, _sp), _rc(_ME, _sp), _rc(_SW, _sp), _rc(_VA, _sp),
                ],
            ),
            # Julius Benson
            AuthorContribution(
                author=Author(name="Julius Benson"),
                credit_levels=[
                    _rc(_IN, _lead),
                ],
            ),
            # Daniel Birman
            AuthorContribution(
                author=Author(
                    name="Daniel Birman",
                ),
                credit_levels=[
                    _rc(_SW, _sp), _rc(_VI, _sp),
                ],
            ),
            # Niccolò Bonacchi
            AuthorContribution(
                author=Author(name="Niccolò Bonacchi"),
                credit_levels=[
                    _rc(_ME, _lead), _rc(_RE, _lead), _rc(_SW, _lead),
                    _rc(_VA, _lead), _rc(_WR, _sp),
                ],
            ),
            # E. Kelly Buchanan
            AuthorContribution(
                author=Author(name="E. Kelly Buchanan"),
                credit_levels=[
                    _rc(_SW, _sp),
                ],
            ),
            # Sebastian Bruijns
            AuthorContribution(
                author=Author(name="Sebastian Bruijns"),
                credit_levels=[
                    _rc(_ME, _sp),
                ],
            ),
            # Matteo Carandini
            AuthorContribution(
                author=Author(name="Matteo Carandini"),
                credit_levels=[
                    _rc(_C, _sp), _rc(_FN, _sp), _rc(_RE, _sp), _rc(_SU, _sp),
                ],
            ),
            # Joana A. Catarino
            AuthorContribution(
                author=Author(name="Joana A. Catarino"),
                credit_levels=[
                    _rc(_IN, _lead),
                ],
            ),
            # Gaelle A. Chapuis
            AuthorContribution(
                author=Author(name="Gaelle A. Chapuis"),
                credit_levels=[
                    _rc(_C, _sp), _rc(_FA, _sp), _rc(_IN, _sp), _rc(_ME, _sp),
                    _rc(_PA, _sp), _rc(_RE, _sp), _rc(_SW, _sp), _rc(_SU, _sp),
                    _rc(_VA, _sp), _rc(_WO, _sp), _rc(_WR, _sp),
                ],
            ),
            # Anne K. Churchland
            AuthorContribution(
                author=Author(name="Anne K. Churchland"),
                credit_levels=[
                    _rc(_C, _sp), _rc(_FN, _lead), _rc(_PA, _lead),
                    _rc(_RE, _lead), _rc(_SU, _lead), _rc(_VA, _lead),
                    _rc(_WR, _sp),
                ],
            ),
            # Yang Dan
            AuthorContribution(
                author=Author(name="Yang Dan"),
                credit_levels=[
                    _rc(_RE, _sp), _rc(_SU, _sp),
                ],
            ),
            # Felicia Davatolhagh
            AuthorContribution(
                author=Author(name="Felicia Davatolhagh"),
                credit_levels=[
                    _rc(_IN, _lead),
                ],
            ),
            # Eric E. J. DeWitt
            AuthorContribution(
                author=Author(name="Eric E. J. DeWitt"),
                credit_levels=[
                    _rc(_C, _lead), _rc(_FN, _sp), _rc(_ME, _sp),
                    _rc(_PA, _sp), _rc(_SW, _sp), _rc(_SU, _sp),
                    _rc(_WR, _sp),
                ],
            ),
            # Tatiana A. Engel
            AuthorContribution(
                author=Author(name="Tatiana A. Engel"),
                credit_levels=[
                    _rc(_FN, _sp), _rc(_SU, _sp),
                ],
            ),
            # Michele Fabbri
            AuthorContribution(
                author=Author(name="Michele Fabbri"),
                credit_levels=[
                    _rc(_SW, _lead),
                ],
            ),
            # Mayo A. Faulkner
            AuthorContribution(
                author=Author(name="Mayo A. Faulkner"),
                credit_levels=[
                    _rc(_SW, _lead),
                ],
            ),
            # Ila Rani Fiete
            AuthorContribution(
                author=Author(name="Ila Rani Fiete"),
                credit_levels=[
                    _rc(_FN, _lead), _rc(_VA, _sp),
                ],
            ),
            # Laura Freitas-Silva
            AuthorContribution(
                author=Author(name="Laura Freitas-Silva"),
                credit_levels=[
                    _rc(_IN, _sp),
                ],
            ),
            # Berk Gerçek
            AuthorContribution(
                author=Author(name="Berk Gerçek"),
                credit_levels=[
                    _rc(_FA, _sp), _rc(_ME, _sp), _rc(_SW, _sp),
                ],
            ),
            # Kenneth D. Harris
            AuthorContribution(
                author=Author(name="Kenneth D. Harris"),
                credit_levels=[
                    _rc(_C, _sp), _rc(_FN, _lead), _rc(_ME, _sp),
                    _rc(_RE, _sp), _rc(_SW, _sp), _rc(_SU, _sp),
                ],
            ),
            # Michael Häusser
            AuthorContribution(
                author=Author(name="Michael Häusser"),
                credit_levels=[
                    _rc(_C, _sp), _rc(_FN, _lead), _rc(_ME, _sp),
                    _rc(_RE, _sp), _rc(_SU, _sp),
                ],
            ),
            # Sonja B. Hofer
            AuthorContribution(
                author=Author(name="Sonja B. Hofer"),
                credit_levels=[
                    _rc(_C, _sp), _rc(_FN, _sp), _rc(_PA, _sp),
                    _rc(_RE, _lead), _rc(_SU, _sp),
                ],
            ),
            # Fei Hu
            AuthorContribution(
                author=Author(name="Fei Hu"),
                credit_levels=[
                    _rc(_IN, _lead),
                ],
            ),
            # Julia M. Huntenburg
            AuthorContribution(
                author=Author(name="Julia M. Huntenburg"),
                credit_levels=[
                    _rc(_SW, _lead),
                ],
            ),
            # Anup Khanal
            AuthorContribution(
                author=Author(name="Anup Khanal"),
                credit_levels=[
                    _rc(_IN, _lead),
                ],
            ),
            # Chris Krasniak
            AuthorContribution(
                author=Author(name="Chris Krasniak"),
                credit_levels=[
                    _rc(_IN, _lead),
                ],
            ),
            # Christopher Langdon
            AuthorContribution(
                author=Author(name="Christopher Langdon"),
                credit_levels=[
                    _rc(_ME, _sp),
                ],
            ),
            # Christopher A. Langfield
            AuthorContribution(
                author=Author(name="Christopher A. Langfield"),
                credit_levels=[
                    _rc(_SW, _sp),
                ],
            ),
            # Peter E. Latham
            AuthorContribution(
                author=Author(name="Peter E. Latham"),
                credit_levels=[
                    _rc(_C, _sp), _rc(_FN, _lead), _rc(_WR, _sp),
                ],
            ),
            # Petrina Y. P. Lau
            AuthorContribution(
                author=Author(name="Petrina Y. P. Lau"),
                credit_levels=[
                    _rc(_IN, _lead),
                ],
            ),
            # Zach Mainen
            AuthorContribution(
                author=Author(name="Zach Mainen"),
                credit_levels=[
                    _rc(_C, _sp), _rc(_FN, _lead), _rc(_RE, _sp),
                    _rc(_SU, _sp), _rc(_WR, _sp),
                ],
            ),
            # Guido T. Meijer
            AuthorContribution(
                author=Author(name="Guido T. Meijer"),
                credit_levels=[
                    _rc(_IN, _lead),
                ],
            ),
            # Nathaniel J. Miska
            AuthorContribution(
                author=Author(name="Nathaniel J. Miska"),
                credit_levels=[
                    _rc(_IN, _lead),
                ],
            ),
            # Thomas D. Mrsic-Flogel
            AuthorContribution(
                author=Author(name="Thomas D. Mrsic-Flogel"),
                credit_levels=[
                    _rc(_FN, _sp), _rc(_RE, _lead), _rc(_SU, _sp),
                ],
            ),
            # Jean-Paul Noel
            AuthorContribution(
                author=Author(name="Jean-Paul Noel"),
                credit_levels=[
                    _rc(_IN, _lead), _rc(_WR, _sp),
                ],
            ),
            # Kai Nylund
            AuthorContribution(
                author=Author(name="Kai Nylund"),
                credit_levels=[
                    _rc(_VI, _sp),
                ],
            ),
            # Alejandro Pan-Vazquez
            AuthorContribution(
                author=Author(name="Alejandro Pan-Vazquez"),
                credit_levels=[
                    _rc(_IN, _lead),
                ],
            ),
            # Liam Paninski
            AuthorContribution(
                author=Author(name="Liam Paninski"),
                credit_levels=[
                    _rc(_FN, _sp), _rc(_ME, _sp), _rc(_RE, _sp),
                    _rc(_SU, _sp), _rc(_WR, _sp),
                ],
            ),
            # Jonathan Pillow
            AuthorContribution(
                author=Author(name="Jonathan Pillow"),
                credit_levels=[
                    _rc(_FA, _sp), _rc(_FN, _sp), _rc(_WR, _sp),
                ],
            ),
            # Cyrille Rossant
            AuthorContribution(
                author=Author(name="Cyrille Rossant"),
                credit_levels=[
                    _rc(_SW, _sp), _rc(_VI, _sp),
                ],
            ),
            # Noam Roth
            AuthorContribution(
                author=Author(name="Noam Roth"),
                credit_levels=[
                    _rc(_IN, _lead),
                ],
            ),
            # Rylan Schaeffer
            AuthorContribution(
                author=Author(name="Rylan Schaeffer"),
                credit_levels=[
                    _rc(_C, _sp), _rc(_FA, _sp), _rc(_ME, _sp),
                    _rc(_PA, _sp), _rc(_SW, _sp), _rc(_VA, _sp),
                ],
            ),
            # Michael Schartner
            AuthorContribution(
                author=Author(name="Michael Schartner"),
                credit_levels=[
                    _rc(_FA, _sp),
                ],
            ),
            # Yanliang Shi
            AuthorContribution(
                author=Author(name="Yanliang Shi"),
                credit_levels=[
                    _rc(_FA, _sp), _rc(_VA, _sp),
                ],
            ),
            # Karolina Z. Socha
            AuthorContribution(
                author=Author(name="Karolina Z. Socha"),
                credit_levels=[
                    _rc(_IN, _lead),
                ],
            ),
            # Nicholas A. Steinmetz
            AuthorContribution(
                author=Author(name="Nicholas A. Steinmetz"),
                credit_levels=[
                    _rc(_ME, _sp), _rc(_SU, _sp), _rc(_WR, _sp),
                ],
            ),
            # Karel Svoboda
            AuthorContribution(
                author=Author(name="Karel Svoboda"),
                credit_levels=[
                    _rc(_FN, _sp), _rc(_ME, _sp), _rc(_SU, _sp),
                ],
            ),
            # Charline Tessereau
            AuthorContribution(
                author=Author(name="Charline Tessereau"),
                credit_levels=[
                    _rc(_WR, _sp),
                ],
            ),
            # Anne E. Urai
            AuthorContribution(
                author=Author(name="Anne E. Urai"),
                credit_levels=[
                    _rc(_IN, _lead),
                ],
            ),
            # Miles J. Wells
            AuthorContribution(
                author=Author(name="Miles J. Wells"),
                credit_levels=[
                    _rc(_SW, _lead),
                ],
            ),
            # Steven Jon West
            AuthorContribution(
                author=Author(name="Steven Jon West"),
                credit_levels=[
                    _rc(_RE, _sp),
                ],
            ),
            # Matthew R. Whiteway
            AuthorContribution(
                author=Author(name="Matthew R. Whiteway"),
                credit_levels=[
                    _rc(_FA, _sp), _rc(_ME, _sp), _rc(_SW, _sp),
                ],
            ),
            # Olivier Winter
            AuthorContribution(
                author=Author(name="Olivier Winter"),
                credit_levels=[
                    _rc(_RE, _sp), _rc(_SW, _lead),
                ],
            ),
            # Ilana B. Witten
            AuthorContribution(
                author=Author(name="Ilana B. Witten"),
                credit_levels=[
                    _rc(_C, _sp), _rc(_FN, _sp), _rc(_SU, _sp),
                ],
            ),
            # Anthony Zador
            AuthorContribution(
                author=Author(name="Anthony Zador"),
                credit_levels=[
                    _rc(_C, _sp), _rc(_FA, _sp), _rc(_IN, _sp), _rc(_SU, _sp),
                ],
            ),
            # Yizi Zhang
            AuthorContribution(
                author=Author(name="Yizi Zhang"),
                credit_levels=[
                    _rc(_FA, _sp), _rc(_VA, _sp),
                ],
            ),
            # Peter Dayan
            AuthorContribution(
                author=Author(name="Peter Dayan"),
                credit_levels=[
                    _rc(_C, _lead), _rc(_FA, _sp), _rc(_FN, _sp), _rc(_ME, _sp),
                    _rc(_PA, _sp), _rc(_SU, _sp), _rc(_VA, _sp), _rc(_VI, _sp),
                    _rc(_WO, _sp), _rc(_WR, _sp),
                ],
            ),
            # Alexandre Pouget
            AuthorContribution(
                author=Author(name="Alexandre Pouget"),
                credit_levels=[
                    _rc(_C, _lead), _rc(_FA, _lead), _rc(_FN, _lead),
                    _rc(_IN, _sp), _rc(_PA, _lead), _rc(_RE, _sp),
                    _rc(_SU, _lead), _rc(_VI, _lead), _rc(_WO, _lead),
                    _rc(_WR, _lead),
                ],
            ),
        ],
    )
