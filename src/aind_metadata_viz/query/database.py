"""DocDB functionality"""

from typing import Optional

import panel as pn
from aind_data_access_api.document_db import MetadataDbClient

from aind_metadata_viz.utils import sort_with_none

docdb_api_client = MetadataDbClient(
    host="api.allenneuraldynamics.org",
    version="v2",
)

DF_KEYS = ["name"]


# Helpers to get option lists
@pn.cache(ttl=86400)  # Cache for 24 hours
def get_project_names():
    project_options = docdb_api_client.aggregate_docdb_records(
        pipeline=[
            {"$group": {"_id": "$data_description.project_name"}},
            {"$sort": {"_id": 1}},  # Optional: sorts alphabetically
        ]
    )
    project_options = [project["_id"] for project in project_options]

    if project_options:
        project_options = sort_with_none(project_options)
    return project_options


@pn.cache(ttl=86400)  # Cache for 24 hours
def get_subject_ids(project_name: Optional[str]):
    """Get subject IDs"""

    if not project_name:
        return []

    subject_options = docdb_api_client.aggregate_docdb_records(
        pipeline=[
            {  # filter by project name
                "$match": {"data_description.project_name": project_name}
            },
            {"$group": {"_id": "$subject.subject_id"}},
        ]
    )
    subject_options = [subject["_id"] for subject in subject_options]
    if subject_options:
        subject_options = sort_with_none(subject_options)
    return subject_options


@pn.cache(ttl=86400)  # Cache for 24 hours
def get_modalities(project_name: Optional[str]):
    """Get modality abbreviations"""

    if not project_name:
        return []

    modality_options = docdb_api_client.aggregate_docdb_records(
        pipeline=[
            {  # filter by project name
                "$match": {"data_description.project_name": project_name}
            },
            {"$unwind": "$data_description.modality"},
            {"$group": {"_id": "$data_description.modality.abbreviation"}},
        ]
    )
    modality_options = [modality["_id"] for modality in modality_options]
    if modality_options:
        modality_options = sort_with_none(modality_options)
    return modality_options


@pn.cache(ttl=86400)  # Cache for 24 hours
def get_session_types(project_name: Optional[str]):
    """Get session types"""

    if not project_name:
        return []

    session_type_options = docdb_api_client.aggregate_docdb_records(
        pipeline=[
            {  # filter by project name
                "$match": {"data_description.project_name": project_name}
            },
            {"$group": {"_id": "$session.session_type"}},
        ]
    )
    session_type_options = [session["_id"] for session in session_type_options]
    if session_type_options:
        session_type_options = sort_with_none(session_type_options)
    return session_type_options


@pn.cache(ttl=60 * 60)  # Cache for 1 hour
def get_docdb_records(filter_query: dict):
    """Get a set of records"""
    return docdb_api_client.retrieve_docdb_records(
        filter_query=filter_query,
        projection={key: 1 for key in DF_KEYS},
    )
