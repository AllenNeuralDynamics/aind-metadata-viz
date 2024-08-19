def check_present(key: str, object: dict):
    """Return true if the value of a key exists and is not None, or any of '' [] {} in a JSON object

    Parameters
    ----------
    field : string
        Key
    object : dict
        Dictionary
    """
    return (
        object[key] is not None
        and object[key] != ""
        and object[key] != []
        and object[key] != {}
        if key in object
        else False
    )


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
