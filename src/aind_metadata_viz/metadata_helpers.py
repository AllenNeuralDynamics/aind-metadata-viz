from aind_metadata_viz.metadata_class_map import first_layer_field_mapping, second_layer_field_mappings, first_layer_versions
from aind_metadata_viz.utils import MetaState
from pydantic import ValidationError
from typing import Literal


def _metadata_present_helper(json: str, check_present: bool = True):
    """Return true if the value of a key exists and is not None, or any of
    '' [] {} in a JSON object

    Parameters
    ----------
    field : string
        Key
    object : dict
        Dictionary
    """
    present = (
        json is not None
        and json != ""
        and json != []
        and json != {}
    )

    if check_present:
        return "present" if present else "absent"
    else:
        return "absent" if present else "present"


def _metadata_valid_helper(field: str, json: str, mapping: dict, ):
    """Return true if the json data is a valid object of the particular field class

    Parameters
    ----------
    json : str
        json string generated from a AindCoreModel dump
    """
    if "schema_version" in json:
        # force the schema version to match the current one
        json["schema_version"] = first_layer_versions[field]

    if field in mapping:
        try:
            return mapping[field](**json) is not None
        except Exception as e:
            print(e)
            return False


def check_metadata_state(field: str, object: dict, parent: str = None, excluded_fields: list = []) -> MetaState:
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
    if field in excluded_fields:
        return MetaState.EXCLUDED.value

    # if you're looking at a parent file's data then you need a different mapping
    if parent:
        print('not implemented')
    # we're at the top level, just check the first layer mappings
    else:
        class_map = first_layer_field_mapping

    # First check that the key exists at all and is not None
    if field in object and object[field]:
        value = object[field]
    else:
        return MetaState.MISSING.value

    # attempt validation
    if _metadata_valid_helper(field, value, class_map):
        return MetaState.VALID.value
    
    # check missing 
    if _metadata_present_helper(value):
        return MetaState.PRESENT.value
    
    return MetaState.MISSING.value


def process_record_list(record_list: list, expected_fields: list, excluded_fields:list = []):
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
    return [{field: check_metadata_state(field, data, excluded_fields) for field in expected_fields} for data in record_list]
