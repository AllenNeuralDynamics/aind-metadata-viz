from aind_data_schema.core.acquisition import Acquisition
from aind_data_schema.core.data_description import DataDescription
from aind_data_schema.core.instrument import Instrument
from aind_data_schema.core.processing import Processing
from aind_data_schema.core.procedures import Procedures
from aind_data_schema.core.quality_control import QualityControl
from aind_data_schema.core.rig import Rig
from aind_data_schema.core.session import Session
from aind_data_schema.core.subject import Subject

field_mapping = {
    "data_description": DataDescription,
    "acquisition": Acquisition,
    "procedures": Procedures,
    "subject": Subject,
    "instrument": Instrument,
    "processing": Processing,
    "rig": Rig,
    "session": Session,
    "quality_control": QualityControl,
}


def check_present(key: str, object: dict, check_present: bool = True):
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
        object[key] is not None
        and object[key] != ""
        and object[key] != []
        and object[key] != {}
        if key in object
        else False
    )
    return present if check_present else not present


def check_valid_metadata(field:str, json: str):
    """Return true if the json data is a valid object of the particular field class

    Parameters
    ----------
    json : str
        json string generated from a AindCoreModel dump
    """
    return field_mapping[field].model_validate_json(json) is not None


def process_present_dict(data: dict, expected_fields: list):
    return {field: check_present(field, data) for field in expected_fields}


def process_present_list(data_list: list, expected_fields: list):
    """Process a data JSON

    Parameters
    ----------
    data_list : _type_
        _description_
    expected_files : _type_
        _description_

    Returns
    -------
    _type_
        _description_
    """
    return [process_present_dict(data, expected_fields) for data in data_list]
