import logging
from aind_data_access_api.rds_tables import RDSCredentials, Client
from aind_data_access_api.document_db import MetadataDbClient
import pandas as pd
import panel as pn

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Redshift settings
REDSHIFT_SECRETS = "/aind/prod/redshift/credentials/readwrite"
RDS_TABLE_NAME = "metadata_upgrade_status_prod"


extra_columns = {
    "_id": 1,
    "data_description.data_level": 1,
    "data_description.project_name": 1,
    "name": 1,
}


@pn.cache()
def get_extra_col_df():
    client = MetadataDbClient(
        host="api.allenneuraldynamics.org",
        version="v1",
    )
    records = client.retrieve_docdb_records(
        filter_query={},
        projection=extra_columns,
        limit=0,
    )
    for i, record in enumerate(records):
        data_description = record.get("data_description", {})
        if data_description:
            record["data_level"] = data_description.get("data_level", None)
            record["project_name"] = data_description.get("project_name", None)
            record.pop("data_description")

        record.pop("_id")
        records[i] = record
    return pd.DataFrame(records)


@pn.cache()
def get_redshift_table():
    rds_client = Client(
        credentials=RDSCredentials(
            aws_secrets_name=REDSHIFT_SECRETS,
        ),
    )
    df = rds_client.read_table(RDS_TABLE_NAME)
    return df


@pn.cache()
def get_data():
    logger.info("Loading extra columns from DocDB...")
    extra_col_df = get_extra_col_df()
    logger.info("Loading Redshift table...")
    df = get_redshift_table()
    if df is None or len(df) == 0:
        return pn.pane.Markdown("**Table is empty or could not be read**")
    logger.info("Merging extra columns...")
    df = df.merge(extra_col_df, how="left", left_on="v1_id", right_on="_id")
    return df


def build_panel_app():
    col = pn.Column("# Metadata Upgrade Status Table", sizing_mode="stretch_width")
    button = pn.widgets.Button(name="Load Table", button_type="primary")

    def load_table(event):
        col.loading = True
        df = get_data()
        tab = pn.widgets.Tabulator(
            df,
            sizing_mode="stretch_width",
            height=800,
            header_filters=True,
            disabled=True,
            page_size=500,
            show_index=False,
        )
        col[:] = ["# Metadata Upgrade Status Table", tab]
        col.loading = False

    button.on_click(load_table)
    col.append(button)
    return col


app = build_panel_app()
app.servable(title="Upgrade Status")
