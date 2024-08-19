from aind_data_access_api.document_db import MetadataDbClient
import numpy as np
import panel as pn

API_GATEWAY_HOST = "api.allenneuraldynamics.org"
DATABASE = "metadata_index"
COLLECTION = "data_assets"

docdb_api_client = MetadataDbClient(
   host=API_GATEWAY_HOST,
   database=DATABASE,
   collection=COLLECTION,
)


@pn.cache
def get_all(test_mode=False):
    filter = {}
    limit = 0 if not test_mode else 10
    paginate_batch_size = 1000
    response = docdb_api_client.retrieve_docdb_records(
        filter_query=filter,
        limit=limit,
        paginate_batch_size=paginate_batch_size
    )

    return response

@pn.cache
def get_subjects():
    filter = {
            'subject.subject_id': {'$exists': True},
            'session': {'$ne': None}
            }
    limit = 1000
    paginate_batch_size = 100
    response = docdb_api_client.retrieve_docdb_records(
        filter_query=filter,
        projection={'_id': 0, 'subject.subject_id': 1},
        limit=limit,
        paginate_batch_size=paginate_batch_size
    )

    # turn this into a list instead of a nested list
    subjects = []
    for data in response:
        subjects.append(np.int32(data['subject']['subject_id']))

    return np.unique(subjects).tolist()


@pn.cache
def get_sessions(subject_id):
    """Get the raw JSON sessions list for a subject

    Parameters
    ----------
    subject_id : string or int
        _description_

    Returns
    -------
    _type_
        _description_
    """
    filter = {"subject.subject_id": str(subject_id),
              "session": {"$ne": "null"}}
    response = docdb_api_client.retrieve_docdb_records(
        filter_query=filter,
        projection={'_id': 0, 'session': 1}
    )

    sessions = []
    for data in response:
        sessions.append(data['session'])

    return sessions
