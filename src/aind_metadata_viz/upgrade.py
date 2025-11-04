from aind_data_access_api.rds_tables import RDSCredentials, Client
from aind_data_access_api.document_db import MetadataDbClient
import pandas as pd
import panel as pn
from aind_metadata_upgrader.upgrade import Upgrade

# Redshift settings
REDSHIFT_SECRETS = "/aind/prod/redshift/credentials/readonly"
RDS_TABLE_NAME = "metadata_upgrade_status_prod"

pn.extension('tabulator')


extra_columns = {
    "_id": 1,
    "data_description.data_level": 1,
    "data_description.project_name": 1,
    "name": 1,
}

client = MetadataDbClient(
    host="api.allenneuraldynamics.org",
    version="v1",
)

TTL_DAY = 24 * 60 * 60
TTL_HOUR = 60 * 60


@pn.cache(ttl=TTL_DAY)
def get_extra_col_df():
    print("Retrieving extra columns from DocDB...")

    all_records = client.retrieve_docdb_records(
        filter_query={},
        projection={"_id": 1},
        limit=0,
    )
    all_ids = [record["_id"] for record in all_records]

    # Batch by 100 to avoid excessively large queries
    batch_size = 100

    records = []
    for start_idx in range(0, len(all_ids), batch_size):
        print(f"Retrieving records {start_idx} to {start_idx + batch_size}...")
        end_idx = start_idx + batch_size
        batch_ids = all_ids[start_idx:end_idx]
        filter_query = {"_id": {"$in": batch_ids}}
        batch_records = client.retrieve_docdb_records(
            filter_query=filter_query,
            projection=extra_columns,
            limit=0,
        )
        records.extend(batch_records)

    for i, record in enumerate(records):
        data_description = record.get("data_description", {})
        if data_description:
            record["data_level"] = data_description.get("data_level", None)
            record["project_name"] = data_description.get("project_name", None)
            record.pop("data_description")

        records[i] = record
    print(f"Retrieved {len(records)} records from DocDB.")
    return pd.DataFrame(records)


@pn.cache(ttl=TTL_HOUR)
def get_redshift_table():
    print("Connecting to Redshift RDS...")
    rds_client = Client(
        credentials=RDSCredentials(
            aws_secrets_name=REDSHIFT_SECRETS,
        ),
    )
    df = rds_client.read_table(RDS_TABLE_NAME)
    print(f"Retrieved {len(df)} records from Redshift table.")
    return df


@pn.cache()
def get_data():
    print("Loading extra columns from DocDB...")
    extra_col_df = get_extra_col_df()
    print("Loading Redshift table...")
    df = get_redshift_table()
    if df is None or len(df) == 0:
        return pn.pane.Markdown("**Table is empty or could not be read**")
    print("Merging extra columns...")
    df = df.merge(extra_col_df, how="left", left_on="v1_id", right_on="_id")
    return df


def run_upgrade(record_id_or_name: str):
    record = None
    # Try to find by _id first
    record = client.retrieve_docdb_records(
        filter_query={"_id": record_id_or_name},
        limit=1,
    )
    if not record:
        # Try to find by name
        record = client.retrieve_docdb_records(
            filter_query={"name": record_id_or_name},
            limit=1,
        )
    if not record:
        return f"Record with _id or name '{record_id_or_name}' not found."

    record = record[0]
    try:
        Upgrade(record)
        return f"Upgrade successful for record '{record_id_or_name}'."
    except Exception as e:
        return f"Upgrade failed for record '{record_id_or_name}': {e}"


def build_panel_app():
    table_col = pn.Column()
    button = pn.widgets.Button(name="Load Table", button_type="primary")

    summary_box = pn.pane.Markdown("", sizing_mode="stretch_width")

    text_input = pn.widgets.TextInput(name="Enter _id or name", placeholder="Type _id or name here...")
    upgrade_button = pn.widgets.Button(name="Run Upgrade", button_type="success")
    output_box = pn.pane.Markdown("", sizing_mode="stretch_width")

    def load_table(event):
        table_col.loading = True
        df = get_data()

        summary_box.object = f"""
**Records upgraded:** {len(df[df['status'] == "success"])}/{len(df)}
"""

        tab = pn.widgets.Tabulator(
            df,
            sizing_mode="stretch_width",
            height=800,
            header_filters=True,
            disabled=True,
            page_size=500,
            show_index=False,
        )
        table_col[:] = ["# Metadata Upgrade Status Table", tab]
        table_col.loading = False

    def run_upgrade_callback(event):
        record_id_or_name = text_input.value
        result = run_upgrade(record_id_or_name)
        output_box.object = f"**Upgrade Output:**\n{result}"

    button.on_click(load_table)
    upgrade_button.on_click(run_upgrade_callback)
    table_col.append(button)
    main_col = pn.Column(
        "# Metadata Upgrade Status Table",
        summary_box,
        table_col,
        pn.Row(text_input, upgrade_button),
        output_box,
        sizing_mode="stretch_width"
    )
    return main_col


app = build_panel_app()
app.servable(title="Upgrade Status")
