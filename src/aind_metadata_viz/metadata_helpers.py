from aind_metadata_viz.metadata_class_map import (
    first_layer_field_mapping,
    second_layer_field_mappings,
    first_layer_versions,
)
from aind_metadata_viz.utils import MetaState, expected_files_from_modalities
from aind_data_schema_models.modalities import FileRequirement
from pydantic import ValidationError
from typing import Literal, Optional, Union


def _metadata_present_helper(value):
    """Return true if the value is not None, or any of '' [] {}

    Parameters
    ----------
    field : string
        Key
    object : dict
        Dictionary
    """
    present = value is not None and value != "" and value != [] and value != {}

    return "present" if present else "absent"


def _metadata_valid_helper(
    field: str,
    json: dict,
    mapping: dict,
):
    """Return true if the json data is a valid object of the particular field class

    Parameters
    ----------
    json : dict
        json dict generated from a AindCoreModel dump
    """
    if "schema_version" in json:
        # force the schema version to match the current one
        json["schema_version"] = first_layer_versions[field]

    if field in mapping:
        expected_type = mapping[field]
        try:
            origin_type = getattr(expected_type, "__origin__", None)

            if origin_type is list:
                item_type = expected_type.__args__[0]
                return all([item_type(**item_json) for item_json in json])
            elif origin_type is Optional:
                # skip optional fields!
                return True
            elif origin_type is Union:
                # Get all possible types in the Union
                union_types = expected_type.__args__

                for union_type in union_types:
                    try:
                        return union_type(**json)
                    except ValidationError:
                        continue
                else:
                    return False
            else:
                # validate as a pydantic model
                return expected_type(**json) is not None
        except Exception as e:
            print(e)
            return False


def check_metadata_state(field: str, object: dict, mapping: dict) -> str:
    """Get the MetaState for a specific key in a dictinoary

    Parameters
    ----------
    key : str
        Field to check
    object : dict
        {field: value}

    Returns
    -------
    MetaState
        _description_
    """
    # if excluded, just return that
    # get the excluded fields from the class map

    if not object:
        return MetaState.MISSING.value

    if (
        "data_description" in object
        and object["data_description"]
        and "modality" in object["data_description"]
    ):
        modality_map = expected_files_from_modalities(
            modalities=object["data_description"]["modality"]
        )

        if field in modality_map:
            file_req = modality_map[field]
        else:
            print(
                f"Warning: field {field} had incorrect modalities, so no file requirement is defined"
            )
            file_req = FileRequirement.REQUIRED
    else:
        # default to required
        print(
            f"Warning: object had no data description modalities, so no file requirement is defined"
        )
        file_req = FileRequirement.REQUIRED

    # Excluded files we ignore, just return that it was excluded
    if file_req == FileRequirement.EXCLUDED:
        return MetaState.EXCLUDED.value

    # First check that the key exists at all and is not None
    if field in object and object[field]:
        value = object[field]
    else:
        if file_req == FileRequirement.OPTIONAL:
            return MetaState.OPTIONAL.value
        else:
            return MetaState.MISSING.value

    # attempt validation
    if _metadata_valid_helper(field, value, mapping):
        return MetaState.VALID.value

    # validation failed, check if the field is present or if it's empty

    # check empty
    if _metadata_present_helper(value):
        return MetaState.PRESENT.value
    else:
        if file_req == FileRequirement.OPTIONAL:
            return MetaState.OPTIONAL.value
        else:
            return MetaState.MISSING.value


def process_record_list(record_list: list, expected_fields: list, parent=None):
    """Process a list of Metadata JSON records from DocDB

    For each record, check each of the expected fields and see if they are valid/present/missing/excluded

    Parameters
    ----------
    data_list : list[dict]
        List of metadata json records as dicts
    expected_fields : list[str]
        List of key fields to check

    Returns
    -------
    list[{field: MetaState}]
    """

    # if you're looking at a parent file's data then you need a different mapping
    if parent:
        class_mapping = second_layer_field_mappings[parent]
    # we're at the top level, just check the first layer mappings
    else:
        class_mapping = first_layer_field_mapping

    return [
        {field: check_metadata_state(field, data, class_mapping) for field in expected_fields}
        for data in record_list
    ]
