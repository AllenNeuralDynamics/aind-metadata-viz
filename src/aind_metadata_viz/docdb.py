from aind_data_access_api.document_db import MetadataDbClient
import numpy as np
import panel as pn
import pandas as pd
import param

from io import StringIO

from aind_data_schema_models.modalities import Modality
from aind_metadata_viz.metadata_helpers import (
    process_record_list,
    _metadata_present_helper,
)
from aind_metadata_viz.utils import compute_count_true, MetaState

API_GATEWAY_HOST = "api.allenneuraldynamics.org"
DATABASE = "metadata_index"
COLLECTION = "data_assets"

docdb_api_client = MetadataDbClient(
    host=API_GATEWAY_HOST,
    database=DATABASE,
    collection=COLLECTION,
)


# reset cache every 24 hours
CACHE_RESET_SEC = 24 * 60 * 60

# Ideally this wouldn't be hard-coded, but pulled from the aind-data-schema repo
EXPECTED_FILES = sorted(
    [
        "data_description",
        "acquisition",
        "procedures",
        "subject",
        "instrument",
        "processing",
        "rig",
        "session",
        "quality_control",
    ]
)

# Ideally this wouldn't be hard-coded but pulled from the aind-data-schema-models repo
MODALITIES = [mod().abbreviation for mod in Modality.ALL]


class Database(param.Parameterized):
    """Local representation of aind-data-schema metadata stored in a
    DocDB MongoDB instance
    """

    derived_filter = param.Boolean(default=False)
    modality_filter = param.String(default="all")

    def __init__(
        self,
        api_host=API_GATEWAY_HOST,
        database=DATABASE,
        collection=COLLECTION,
        test_mode=False,
    ):
        """Initialize"""
        # get data
        self._data = get_all(test_mode=test_mode)

        # setup
        self.set_file()

    @property
    def data_filtered(self):
        mod_filter = not (self.modality_filter == "all")
        derived_filter = self.derived_filter == True

        if mod_filter or derived_filter:
            # filter data
            filtered_list = []

            for data in self._data:
                include: bool = True

                if mod_filter and not (
                    data["data_description"]
                    and "modality" in data["data_description"]
                    and isinstance(data["data_description"]["modality"], list)
                    and any(
                        mod["abbreviation"] == self.modality_filter
                        for mod in data["data_description"]["modality"]
                    )
                ):
                    include = False

                if derived_filter and data["name"].count("_") <= 3:
                    include = False

                if include:
                    filtered_list.append(data)
            return filtered_list
        else:
            return self._data

    def get_file_presence(self, files: list = EXPECTED_FILES):
        """Get the presence of a list of files

        Parameters
        ----------
        files : list[str], optional
            List of expected metadata filenames, by default EXPECTED_FILES
        """
        # Get the short form df, each row is a record and each column is it's file:MetaState
        processed = process_record_list(self.data_filtered, files)
        df = pd.DataFrame(processed, columns=files)

        # Melt to long form
        df_melted = df.melt(var_name='file', value_name='state')
        # Get sum
        df_summary = df_melted.groupby(["file", "state"]).size().reset_index(name="sum")

        return df_summary

    def get_field_presence(self):
        """Get the presence of fields at the top-level"""
        if len(self.data_filtered) > 0:
            fields = [
                item
                for item in list(self.data_filtered[0].keys())
                if item not in EXPECTED_FILES
            ]
        else:
            fields = []

        return self.get_file_presence(files=fields)

    def set_file(self, file: str = EXPECTED_FILES[0]):
        """Set the active file

        Parameters
        ----------
        file : str, optional
            Active filename, by default EXPECTED_FILES[0]
        """
        self.file = file

        self.mid_list = []
        for data in self.data_filtered:
            if _metadata_present_helper(data[self.file]):
                self.mid_list.append(data[self.file])

    def get_file_field_presence(self):
        """Get the presence of fields in a specific file

        Parameters
        ----------
        file : str
            _description_

        Returns
        -------
        _type_
            _description_
        """
        return pd.DataFrame()
        # expected_fields = (
        #     self.mid_list[0].keys() if len(self.mid_list) > 0 else []
        # )
        # processed = process_record_list(self.mid_list, expected_fields)

        # print(processed)
        # df = pd.DataFrame()
        # df = pd.DataFrame(processed, columns=expected_fields)

        # return compute_count_true(df)

    def get_csv(self, file: str, field: str = " ", missing: str = "Missing"):
        """Build a CSV file of export data based on the selected file and field

        Parameters
        ----------
        file : string
            Metadata file name to filter on
        field : string
            Field name to filter on

        Returns
        -------
        csv
            CSV file with name, _id, location, and creation date
        """
        # For everybody who is missing the currently active file/field
        id_fields = ["name", "_id", "location", "creation"]

        get_present = missing == "Present"

        df_data = []
        for data in self.data_filtered:
            if not data[file] is None:
                if field == " " or _metadata_present_helper(
                    field, data[file], check_present=get_present
                ):
                    # This file/field combo is present/missing, get all the id
                    # information
                    id_data = {}
                    for id_field in id_fields:
                        if id_field in data:
                            id_data[id_field] = data[id_field]
                        else:
                            id_data[id_field] = None
                    df_data.append(id_data)

        df = pd.DataFrame(df_data)

        sio = StringIO()
        df.to_csv(sio, index=False)
        return sio.getvalue()


@pn.cache(ttl=CACHE_RESET_SEC)
def get_all(test_mode=False):
    filter = {}
    # limit = 0 if not test_mode else 10
    limit = 10
    paginate_batch_size = 500
    response = docdb_api_client.retrieve_docdb_records(
        filter_query=filter,
        limit=limit,
        paginate_batch_size=paginate_batch_size,
    )

    return response