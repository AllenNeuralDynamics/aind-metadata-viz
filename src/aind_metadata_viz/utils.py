from enum import Enum
from aind_data_schema_models.modalities import ExpectedFiles, FileRequirement

# from aind_data_schema.core.metadata import CORE_FILES  # todo: import instead of declaring

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


class MetaState(str, Enum):
    VALID = "valid"
    PRESENT = "present"
    OPTIONAL = "optional"
    MISSING = "missing"
    EXCLUDED = "excluded"


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
