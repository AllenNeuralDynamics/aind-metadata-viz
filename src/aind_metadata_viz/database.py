from aind_data_access_api.document_db import MetadataDbClient
from zombie_squirrel import custom, asset_basics
from aind_metadata_validator.metadata_validator import validate_metadata
import panel as pn
import pandas as pd
import param
import numpy as np
import io
import logging
import time
from io import StringIO
from pathlib import Path

from aind_data_schema.core.metadata import CORE_FILES
from aind_data_schema_models.modalities import (
    Modality,
)
from aind_metadata_validator.mappings import (
    SECOND_LAYER_MAPPING,
)
from aind_metadata_viz.utils import METASTATE_MAP, hd_style

DEV_OR_PROD = "prod"
VALIDATOR_TABLE_NAME = f"metadata_status_{DEV_OR_PROD}_v2"

CHUNK_SIZE = 1000
PARQUET_CACHE_PATH = Path.home() / "metadata_cache.parquet"

docdb_api_client = MetadataDbClient(
    host="api.allenneuraldynamics.org",
    version="v2",
)


# These are the fields that need to be dropped from that data frame when building charts
EXTRA_FIELDS = ["modalities", "derived", "name", "_id", "location"]

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
        self.data = _load_data(test_mode=test_mode)
        self.set_file(CORE_FILES[0])
        self.set_field("")

    @property
    def data_filtered(self):
        """Return the data filtered by the active filters

        Returns
        -------
        _type_
            _description_
        """
        mask = pd.Series(True, index=self.data.index)

        if not (self.modality_filter == "all"):
            mask = mask & self.data["modalities"].str.contains(self.modality_filter)

        if not (self.derived_filter == "All assets"):
            mask = mask & (self.data["derived"] == (self.derived_filter == "Derived"))

        return self.data[mask]

    def data_modality_filtered(self, modality: str):
        """Pull out only data records which include a particular modality

        Then collapse all files together for that modality, dropping excluded files

        Parameters
        ----------
        modality : str
            Modality.ONE_OF
        """
        mask = pd.Series(True, index=self.data.index)

        if not (self.derived_filter == "All assets"):
            mask = mask & (self.data["derived"] == (self.derived_filter == "Derived"))

        mask = mask & self.data["modalities"].apply(lambda x: modality in x.split(","))

        return self.data.loc[mask, CORE_FILES + EXTRA_FIELDS]

    def get_overall_valid(self):
        """Get the percentage of valid records"""
        return (
            np.sum(self.data["metadata"].values == "valid")
            / len(self.data)
            * 100
        )

    def get_file_presence(self):
        """Get the presence of a list of files

        Parameters
        ----------
        files : list[str], optional
            List of expected metadata filenames, by default EXPECTED_FILES
        """
        # Melt to long form
        df = self.data_filtered[CORE_FILES]

        df_melted = df.melt(var_name="file", value_name="state")
        # Get sum
        df_summary = (
            df_melted.groupby(["file", "state"]).size().reset_index(name="sum")
        )

        return df_summary

    def get_modality_presence(self, modality: str):
        """Get the presence for a specific modality"""

        df_filtered = self.data_modality_filtered(modality)
        df_filtered.drop(
            ["derived", "name", "_id", "location", "modalities"],
            axis=1,
            inplace=True,
        )

        # Collapse all columns
        df_melted = df_filtered.melt(
            id_vars=[], var_name="file", value_name="state"
        )

        # Get sum
        df_summary = (
            df_melted.groupby(["state"]).size().reset_index(name="sum")
        )
        df_summary["sum"] = df_summary["sum"] / np.sum(df_summary["sum"])

        df_summary["modality"] = modality

        return df_summary

    def set_file(self, file: str):
        """Set the active file

        Parameters
        ----------
        file : str, optional
            Active filename
        """
        self.file = file

        self.field_list = list(SECOND_LAYER_MAPPING[file].keys())

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
        """Get the presence of fields in a specific file"""
        mask = pd.Series(True, index=self.data.index)

        if not (self.derived_filter == "All assets"):
            mask = mask & (self.data["derived"] == (self.derived_filter == "Derived"))

        if not self.modality_filter == "all":
            mask = mask & self.data["modalities"].apply(
                lambda x: self.modality_filter in x.split(",")
            )

        field_df = self.data[mask].filter(regex=rf"^{self.file}\.").rename(
            columns=lambda col: col.replace(f"{self.file}.", "")
        )

        df_melted = field_df.melt(
            id_vars=[], var_name="field", value_name="state"
        )
        df_summary = (
            df_melted.groupby(["field", "state"])
            .size()
            .reset_index(name="sum")
        )

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
            CSV file with name, _id, location, and subject_id (if available)
        """
        df_filtered = self.data_filtered

        type0 = "missing" if vp_state == "Missing" else "present"
        type1 = "optional" if vp_state == "Missing" else "valid"

        if self.field:
            field_col = f"{self.file}.{self.field}"
            row_filter = (
                (df_filtered[self.file] == type0)
                | (df_filtered[self.file] == type1)
            ) | (
                (df_filtered[field_col] == type0)
                | (df_filtered[field_col] == type1)
            )
        else:
            row_filter = (df_filtered[self.file] == type0) | (
                df_filtered[self.file] == type1
            )

        df = df_filtered.loc[row_filter, ["name", "_id", "location"]]

        sio = StringIO()
        df.to_csv(sio, index=False)
        return sio.getvalue()


@pn.cache(ttl=CACHE_RESET_DAY)
def _get_status() -> pd.DataFrame:
    """Get the status of the metadata"""
    response = custom(VALIDATOR_TABLE_NAME)

    # replace values using the int -> string map
    response.replace(METASTATE_MAP, inplace=True)

    # Convert value columns to category dtype (~8x less memory than object strings)
    cat_cols = [c for c in response.columns if c != "_id"]
    response[cat_cols] = response[cat_cols].astype("category")

    return response


@pn.cache(ttl=CACHE_RESET_DAY)
def _get_metadata(test_mode=False) -> pd.DataFrame:
    df = asset_basics()[["_id", "name", "location", "modalities", "data_level"]].copy()
    df["modalities"] = df["modalities"].fillna("").str.replace(", ", ",", regex=False)
    df["derived"] = df["data_level"] != "raw"
    df.drop(columns=["data_level"], inplace=True)
    return df


def _load_data(test_mode=False) -> pd.DataFrame:
    """Load the merged DataFrame from a parquet cache if fresh, otherwise fetch from the API.

    The parquet file is stored at ~/metadata_cache.parquet and is considered fresh
    if it is less than CACHE_RESET_DAY seconds old.
    """
    if not test_mode and PARQUET_CACHE_PATH.exists():
        age = time.time() - PARQUET_CACHE_PATH.stat().st_mtime
        if age < CACHE_RESET_DAY:
            return pd.read_parquet(PARQUET_CACHE_PATH)

    file_data = _get_metadata(test_mode=test_mode)
    status_data = _get_status()
    data = pd.merge(file_data, status_data, on="_id", how="inner")

    if not test_mode:
        data.to_parquet(PARQUET_CACHE_PATH)

    return data


@pn.cache(ttl=CACHE_RESET_HOUR)
def _get_record_by_name(name: str) -> list:
    """Get a single record by name"""

    if not name:
        return []

    records = docdb_api_client.retrieve_docdb_records(
        filter_query={"name": name}
    )
    return records


class RecordValidator:

    def __init__(self, id, colors):
        """Populate the validator with a record and run validation

        Parameters
        ----------
        id : _type_
            _description_
        """
        self.update(id)
        self.state = None
        self.log = None
        self.colors = colors

    def update(self, name):

        records = _get_record_by_name(name)

        if len(records) > 0:
            self.record = records[0]
        else:
            self.state = None
            self.log = None
            return

        # Create an in-memory buffer to capture log output
        log_capture_string = io.StringIO()

        # Set up a custom handler that writes to the buffer
        ch = logging.StreamHandler(log_capture_string)
        ch.setLevel(logging.INFO)  # Adjust level as needed

        # Get the logger used in `validate_metadata`
        logger = logging.getLogger()
        logger.addHandler(ch)

        # run the validator, capturing any errors
        self.state = validate_metadata(self.record)

        ch.flush()
        self.log = log_capture_string.getvalue()
        logger.removeHandler(ch)
        log_capture_string.close()

    def panel(self):
        """Return a panel object with the validation results"""
        if self.state is None:
            return pn.pane.Markdown("No record was found.")
        else:
            print(self.state["metadata"].value)
            state = pn.pane.Markdown(
                f"""
Overall metadata: {hd_style(METASTATE_MAP[self.state["metadata"].value], self.colors)}
"""
            )
            file_state = {}
            for file in CORE_FILES:
                file_state[file] = hd_style(
                    METASTATE_MAP[self.state[file].value], self.colors
                )
            print(file_state)
            df = pd.DataFrame(file_state, index=[0])
            file_state = pn.pane.DataFrame(df, width=920, escape=False)

            log = pn.pane.Markdown(self.log, width=920)

            return pn.Column(state, file_state, log, width=515)
        # return (self.state, self.log)
