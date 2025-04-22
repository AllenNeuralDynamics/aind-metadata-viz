from enum import Enum
from aind_data_schema_models.modalities import ExpectedFiles, FileRequirement

# from aind_data_schema.core.metadata import CORE_FILES  # todo: import instead of declaring

outer_style = {
    'background': '#ffffff',
    'border-radius': '5px',
    'border': '2px solid black',
    'padding': '10px',
    'box-shadow': '5px 5px 5px #bcbcbc',
    'margin': "5px",
}

CORE_FILES = [
    "subject",
    "data_description",
    "procedures",
    "session",
    "rig",
    "processing",
    "acquisition",
    "instrument",
    "quality_control",
]


METASTATE_MAP = {
    2: "valid",
    1: "present",
    0: "optional",
    -1: "missing",
    -2: "excluded",
    -3: "corrupt",
}


class MetadataState(int, Enum):
    VALID = 2  # validates as it's class
    PRESENT = 1  # present
    OPTIONAL = 0  # missing, but it's optional
    MISSING = -1  # missing, and it's required
    EXCLUDED = -2  # excluded for all modalities in the metadata
    CORRUPT = -3  # corrupt, can't be loaded from json


REMAPS = {
    "OPHYS": "POPHYS",
    "EPHYS": "ECEPHYS",
    "TRAINED_BEHAVIOR": "BEHAVIOR",
    "HSFP": "FIB",
    "DISPIM": "SPIM",
    "MULTIPLANE_OPHYS": "POPHYS",
    "SMARTSPIM": "SPIM",
    "FIP": "FIB",
    "SINGLE_PLANE_OPHYS": "POPHYS",
    "EXASPIM": "SPIM",
}

AIND_COLORS = {
    "dark_blue": "#003057",
    "light_blue": "#2A7DE1",
    "green": "#1D8649",
    "yellow": "#FFB71B",
    "grey": "#7C7C7F",
    "red": "#FF5733",
}

COLOR_OPTIONS = {
    "default": {
        "valid": AIND_COLORS["green"],
        "present": AIND_COLORS["light_blue"],
        "optional": "grey",
        "missing": "red",
        "excluded": "#F0F0F0",
    },
    "lemonade": {
        "valid": "#F49FD7",
        "present": "#FFD966",
        "optional": "grey",
        "missing": "#9FF2F5",
        "excluded": "white",
    },
    "aind": {
        "valid": AIND_COLORS["green"],
        "present": AIND_COLORS["light_blue"],
        "optional": AIND_COLORS["grey"],
        "missing": AIND_COLORS["red"],
        "excluded": "white",
    }
}


def hd_style(text, colors):
    return (
        f"<span style='font-weight: bold; color:{colors[text]}'>{text}</span>"
    )


def expected_files_from_modalities(
    modalities: list[str],
) -> dict[str, FileRequirement]:
    """Get the expected files for a list of modalities

    Parameters
    ----------
    modalities : list[str]
        List of modalities to get expected files for

    Returns
    -------
    list[str]
        List of expected files
    """
    requirement_dict = {}

    # I can't believe I have to do this
    if not isinstance(modalities, list):
        modalities = [modalities]

    for modality in modalities:
        if "abbreviation" not in modality:
            continue

        for file in CORE_FILES:
            #  For each field, check if this is a required/excluded file

            # remap 
            abbreviation = str(modality["abbreviation"]).replace("-", "_").upper()
            if abbreviation in REMAPS:
                abbreviation = REMAPS[abbreviation]

            file_requirement = getattr(
                getattr(
                    ExpectedFiles,
                    abbreviation,
                ),
                file,
            )

            if file not in requirement_dict:
                requirement_dict[file] = file_requirement
            elif (file_requirement == FileRequirement.REQUIRED) or (
                file_requirement == FileRequirement.OPTIONAL
                and requirement_dict[file] == FileRequirement.EXCLUDED
            ):
                # override, required wins over all else, and optional wins over excluded
                requirement_dict[file] = file_requirement

    return requirement_dict
