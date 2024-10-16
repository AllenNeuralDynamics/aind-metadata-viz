from aind_data_access_api.document_db import MetadataDbClient
import panel as pn
import pandas as pd
import param
import os
import numpy as np

from io import StringIO

from aind_data_schema_models.modalities import (
    Modality,
    ExpectedFiles,
    FileRequirement,
)
from aind_metadata_viz.metadata_helpers import (
    process_record_list,
)
from aind_metadata_viz.metadata_class_map import (
    first_layer_field_mapping,
    second_layer_field_mappings,
)

API_GATEWAY_HOST = os.getenv("API_GATEWAY_HOST", "api.allenneuraldynamics-test.org")
DATABASE = os.getenv("DATABASE", "metadata_index")
COLLECTION = os.getenv("COLLECTION", "data_assets")

docdb_api_client = MetadataDbClient(
    host=API_GATEWAY_HOST,
    database=DATABASE,
    collection=COLLECTION,
)

ALL_FILES = sorted(
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
# These are the fields that need to be dropped from that data frame when building charts
EXTRA_FIELDS = ["modalities", "derived", "name", "_id", "location", "created"]

# reset cache every 24 hours
CACHE_RESET_DAY = 24 * 60 * 60
CACHE_RESET_HOUR = 60 * 60

MODALITIES = [mod().abbreviation for mod in Modality.ALL]


class Database(param.Parameterized):
    """Local representation of aind-data-schema metadata stored in a
    DocDB MongoDB instance
    """

    modality_filter = param.String(default="all")
    derived_filter = param.String(default="All assets")

    def __init__(
        self,
        test_mode=False,
    ):
        """Initialize"""
        # get data
        self._file_data = _get_file_presence(test_mode=test_mode)
        self._field_data = _get_field_presence(test_mode=test_mode)

        # setup
        (expected_files, _) = self.get_expected_files()
        self.set_file(expected_files[0])
        self.set_field("")

    @property
    def data_filtered(self):
        """Return the data filtered by the active filters

        Returns
        -------
        _type_
            _description_
        """
        mod_filter = not (self.modality_filter == "all")

        filtered_df = self._file_data.copy()

        # Filter by modality
        if mod_filter:
            filtered_df = filtered_df[
                filtered_df["modalities"].str.contains(self.modality_filter)
            ]

        if not (self.derived_filter == "All assets"):
            filtered_df = filtered_df[filtered_df["derived"] == (self.derived_filter == "Derived")]

        return filtered_df

    def data_modality_filtered(self, modality: str):
        """Pull out only data records which include a particular modality

        Then collapse all files together for that modality, dropping excluded files

        Parameters
        ----------
        modality : str
            Modality.ONE_OF
        """
        filtered_df = self._file_data.copy()

        # Apply derived filter
        if not (self.derived_filter == "All assets"):
            filtered_df = filtered_df[filtered_df["derived"] == (self.derived_filter == "Derived")]

        filtered_df = filtered_df[filtered_df['modalities'].apply(lambda x: modality in x.split(','))]

        return filtered_df

    def get_expected_files(self) -> tuple[list[str], list[str]]:
        if self.modality_filter == "all":
            return (ALL_FILES, [])

        expected_files_by_modality = ALL_FILES.copy()
        excluded_files_by_modality = []

        # get the ExpectedFiles object for this modality
        expected_files = getattr(
            ExpectedFiles, str(self.modality_filter).upper()
        )

        # loop through the actual files and remove any that are not expected
        for file in expected_files_by_modality:
            if getattr(expected_files, file) == FileRequirement.EXCLUDED:
                expected_files_by_modality.remove(file)
                excluded_files_by_modality.append(file)

        return (expected_files_by_modality, excluded_files_by_modality)

    def get_file_presence(self):
        """Get the presence of a list of files

        Parameters
        ----------
        files : list[str], optional
            List of expected metadata filenames, by default EXPECTED_FILES
        """
        # Melt to long form
        df = self.data_filtered.copy()
        df.drop(EXTRA_FIELDS, axis=1, inplace=True)

        df_melted = df.melt(var_name="file", value_name="state")
        # Get sum
        df_summary = df_melted.groupby(["file", "state"]).size().reset_index(name="sum")

        return df_summary

    def get_modality_presence(self, modality: str):
        """Get the presence for a specific modality
        """

        df_filtered = self.data_modality_filtered(modality)
        df_filtered.drop(['derived', 'name', '_id', 'location', 'created', 'modalities'], axis=1, inplace=True)

        # Collapse all columns
        df_melted = df_filtered.melt(
            id_vars=[],
            var_name="file",
            value_name="state"
        )

        # Get sum
        df_summary = df_melted.groupby(["state"]).size().reset_index(name="sum")
        df_summary["sum"] = df_summary["sum"] / np.sum(df_summary["sum"])

        df_summary['modality'] = modality

        return df_summary

    def set_file(self, file: str):
        """Set the active file

        Parameters
        ----------
        file : str, optional
            Active filename
        """
        self.file = file

        self.field_list = list(second_layer_field_mappings[file].keys())

    def set_field(self, field: str):
        """Set the active field

        Parameters
        ----------
        field : str
            Active field name
        """
        if field != "" and field not in self.field_list:
            raise ValueError(f"Field {field} not in field list")

        self.field = field

    def get_file_field_presence(self):
        """Get the presence of fields in a specific file
        """
        field_df = self._field_data[self.file]

        # we need to filter by the derived/modality filters here but they are in the other dataframe
        if not (self.derived_filter == "All assets"):
            field_df = field_df[self._file_data["derived"] == (self.derived_filter == "Derived")]

        if not self.modality_filter == "all":
            field_df = field_df[self._file_data['modalities'].apply(lambda x: self.modality_filter in x.split(','))]

        df_melted = field_df.melt(
            id_vars=[],
            var_name="field",
            value_name="state"
        )
        df_summary = df_melted.groupby(["field", "state"]).size().reset_index(name="sum")

        return df_summary

    def get_csv(self, vp_state: str = "Not Valid/Present"):
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
            CSV file with name, _id, location, created date, and subject_id (if available)
        """
        # For everybody who is missing the currently active file/field
        df = self.data_filtered

        df = df[["name", "_id", "location", "created"]]

        type0 = "missing" if vp_state == "Missing" else "present"
        type1 = "optional" if vp_state == "Missing" else "valid"

        if self.field:
            filter = ((self.data_filtered[self.file] == type0) | (self.data_filtered[self.file] == type1)) | \
                      ((self._field_data[self.field] == type0) | (self._field_data[self.field] == type1))
        else:
            filter = (self.data_filtered[self.file] == type0) | (self.data_filtered[self.file] == type1)

        df = df[filter]

        sio = StringIO()
        df.to_csv(sio, index=False)
        return sio.getvalue()


@pn.cache(ttl=CACHE_RESET_DAY)
def _get_file_presence(test_mode=False) -> pd.DataFrame:
    """Get all and convert to data frame format

    Parameters
    ----------
    test_mode : bool, optional
        _description_, by default False
    """
    record_list = _get_all(test_mode=test_mode)
    processed = process_record_list(record_list, ALL_FILES)

    # Now add some information about the records, i.e. modality, derived state, etc.
    for i, record in enumerate(record_list):
        if (
            "data_description" in record
            and record["data_description"]
            and "modality" in record["data_description"]
        ):
            if isinstance(record["data_description"]["modality"], list):
                modalities = [
                    mod["abbreviation"]
                    for mod in record["data_description"]["modality"]
                ]
        else:
            modalities = []
        derived = True if record["name"].count("_") <= 3 else False

        info_data = {
            "modalities": ",".join(modalities),
            "derived": derived,
            "name": record["name"],
            "_id": record["_id"],
            "location": record["location"],
            "created": record["created"],
        }

        processed[i] = {**processed[i], **info_data}

    return pd.DataFrame(
        processed,
        columns=ALL_FILES
        + ["modalities", "derived", "name", "_id", "location", "created"],
    )


@pn.cache(ttl=CACHE_RESET_DAY)
def _get_field_presence(test_mode=False) -> dict:
    """Get all and convert to data frame format

    returns a dictionary {file: field_df}
    """
    record_list = _get_all(test_mode=test_mode)

    file_dfs = {}
    # filter by file
    for file in ALL_FILES:
        expected_fields = second_layer_field_mappings[file]
        # get field presence
        field_record_list = [record[file] if file in record else None for record in record_list]
        processed = process_record_list(field_record_list, expected_fields, parent=file)

        file_df = pd.DataFrame(processed, columns=expected_fields)

        file_dfs[file] = file_df

    return file_dfs

@pn.cache(ttl=CACHE_RESET_DAY)
def _get_all(test_mode=False):
    filter = {}
    limit = 0 if not test_mode else 10
    paginate_batch_size = 500
    response = docdb_api_client.retrieve_docdb_records(
        filter_query=filter,
        limit=limit,
        paginate_batch_size=paginate_batch_size,
    )

    return response
