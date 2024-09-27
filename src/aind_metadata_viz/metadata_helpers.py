def check_present(key: str, object: dict, check_present: bool = True):
    """Return "present" if the value of a key exists and is not None, or any of
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

    if check_present:
        return "present" if present else "absent"
    else:
        return "absent" if present else "present"


def process_present_dict(
    data: dict, expected_fields: list[str], excluded_fields: list[str]
):
    pdict = {}

    for field in expected_fields:
        pdict[field] = check_present(field, data)

    for field in excluded_fields:
        pdict[field] = "excluded"

    return pdict


def process_present_list(
    data_list: list, expected_fields: list[str], excluded_fields: list[str]
):
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
    return [
        process_present_dict(data, expected_fields, excluded_fields)
        for data in data_list
    ]

def process_present_list_all(
    data_list: list, expected_fields: list[str], excluded_fields: list[str]
):
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
    return [
        process_present_dict(data, expected_fields, excluded_fields)
        for data in data_list
    ]
