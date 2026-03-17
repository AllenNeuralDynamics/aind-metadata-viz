from aind_data_access_api.document_db import MetadataDbClient
from zombie_squirrel import custom
import altair as alt
import pandas as pd
import panel as pn
from aind_metadata_upgrader.upgrade import Upgrade
from aind_metadata_viz.utils import AIND_COLORS, outer_style
from aind_data_schema import __version__ as schema_version
import copy
import json
import traceback

# Redshift settings
REDSHIFT_SECRETS = "/aind/prod/redshift/credentials/readonly"
RDS_TABLE_NAME = "metadata_upgrade_status_prod"

pn.extension("tabulator")


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
    df = custom(RDS_TABLE_NAME)
    print(f"Retrieved {len(df)} records from Redshift table.")
    return df


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
    """
    Perform detailed upgrade testing with field-by-field breakdown.

    Two-step process:
    1. Try full asset upgrade
    2. If fails, test each field individually with skip_metadata_validation=True

    Returns dict with detailed results for each field.
    """
    # Core files to test, with field conversion mapping
    FIELD_CONVERSION_MAP = {
        "session": "acquisition",
        "rig": "instrument",
    }

    CORE_FILES = [
        "data_description",
        "procedures",
        "subject",
        "session",
        "rig",
        "processing",
        "quality_control",
    ]

    # Retrieve record
    record = client.retrieve_docdb_records(
        filter_query={"_id": record_id_or_name},
        limit=1,
    )
    if not record:
        record = client.retrieve_docdb_records(
            filter_query={"name": record_id_or_name},
            limit=1,
        )
    if not record:
        return {
            "error": f"Record with _id or name '{record_id_or_name}' not found.",
            "overall_success": False,
        }

    record = record[0]
    asset_name = record.get("name", record.get("_id", "Unknown"))

    # Deep copy original record for comparison
    original_record = copy.deepcopy(record)

    # Initialize results structure
    results = {
        "overall_success": False,
        "overall_error": None,
        "overall_traceback": None,
        "asset_name": asset_name,
        "asset_id": record.get("_id"),
        "files_tested": {},
    }

    # STEP 1: Try full asset upgrade
    try:
        upgrader = Upgrade(copy.deepcopy(record))
        upgraded_metadata = upgrader.metadata.model_dump()

        # Success! Extract per-field data
        results["overall_success"] = True

        for core_file in CORE_FILES:
            if core_file in original_record and original_record[core_file]:
                # Handle field conversion
                converted_to = FIELD_CONVERSION_MAP.get(core_file)
                target_field = converted_to if converted_to else core_file

                results["files_tested"][core_file] = {
                    "success": True,
                    "error": None,
                    "v1_data": original_record[core_file],
                    "v2_data": upgraded_metadata.get(target_field),
                    "converted_to": converted_to,
                }

        return results

    except Exception as e:
        # Full upgrade failed, capture error
        results["overall_error"] = str(e)
        results["overall_traceback"] = traceback.format_exc()

    # STEP 2: Field-by-field testing with skip_metadata_validation=True
    for core_file in CORE_FILES:
        if core_file not in original_record or not original_record[core_file]:
            continue  # Skip files not present in record

        converted_to = FIELD_CONVERSION_MAP.get(core_file)

        # Create minimal test dict with just this field + subject
        test_dict = {
            core_file: copy.deepcopy(original_record[core_file]),
        }

        # Add subject as companion data if testing other files
        if core_file != "subject" and "subject" in original_record:
            test_dict["subject"] = copy.deepcopy(original_record["subject"])

        # Add required metadata fields
        test_dict["_id"] = record.get("_id", "test")
        test_dict["name"] = record.get("name", "test")
        test_dict["location"] = record.get("location", "")

        try:
            field_upgrader = Upgrade(test_dict, skip_metadata_validation=True)
            field_upgraded = field_upgrader.metadata.model_dump()

            target_field = converted_to if converted_to else core_file

            results["files_tested"][core_file] = {
                "success": True,
                "error": None,
                "v1_data": original_record[core_file],
                "v2_data": field_upgraded.get(target_field),
                "converted_to": converted_to,
            }

        except Exception as e:
            results["files_tested"][core_file] = {
                "success": False,
                "error": str(e),
                "traceback": traceback.format_exc(),
                "v1_data": original_record[core_file],
                "v2_data": None,
                "converted_to": converted_to,
            }

    # Determine if any fields succeeded
    successful_fields = [
        f for f, r in results["files_tested"].items() if r["success"]
    ]
    results["partial_success"] = len(successful_fields) > 0

    return results


def display_upgrade_results(results):
    """
    Build Panel UI components to display upgrade results with collapsible
    side-by-side JSON comparisons.
    """
    if "error" in results and not results.get("overall_success"):
        return pn.pane.Markdown(
            f"**Error:** {results['error']}",
            styles={"color": AIND_COLORS["red"]},
        )

    # Light style for JSON boxes (matching Flask original)
    json_box_style = {
        "background": "#f8f9fa",
        "border": "1px solid #dee2e6",
        "border-radius": "5px",
        "padding": "15px",
        "margin": "5px",
    }

    main_col = pn.Column(sizing_mode="stretch_width")

    # Overall status header
    asset_name = results.get("asset_name", "Unknown")
    if results["overall_success"]:
        status_color = AIND_COLORS["green"]
        status_text = "SUCCESS: Full upgrade successful"
    elif results.get("partial_success"):
        status_color = AIND_COLORS["yellow"]
        status_text = "PARTIAL: Some fields failed"
    else:
        status_color = AIND_COLORS["red"]
        status_text = "FAILED: Upgrade failed"

    header_md = f"## Upgrade Results for: {asset_name}\n\n"
    header_md += f"<span style='color:{status_color}; font-weight:bold;'>{status_text}</span>\n"
    header_md += (
        f"Schema upgrade: <code>v1.x</code> -> <code>v{schema_version}</code>"
    )
    main_col.append(pn.pane.Markdown(header_md))

    # Summary statistics panel
    files_tested = results.get("files_tested", {})
    total_files = len(files_tested)
    successful_files = sum(
        1 for f in files_tested.values() if f.get("success", False)
    )
    failed_files = total_files - successful_files

    if total_files > 0:
        summary_text = f"**Summary:** {total_files} files tested\n\n"
        summary_text += f"<span style='color:{AIND_COLORS['green']}'>{successful_files} successful</span> | "
        summary_text += f"<span style='color:{AIND_COLORS['red']}'>{failed_files} failed</span>"

        summary_pane = pn.pane.Markdown(
            summary_text,
            styles={
                "background": "#f8f9fa",
                "border": "1px solid #dee2e6",
                "border-radius": "5px",
                "padding": "15px",
                "margin": "15px 0",
            },
        )
        main_col.append(summary_pane)

    # Overall error message if present
    if results.get("overall_error"):
        error_md = f"\n\n**Overall Error:** {results['overall_error']}"
        main_col.append(
            pn.pane.Markdown(error_md, styles={"color": AIND_COLORS["red"]})
        )

    # Process each file
    files_tested = results.get("files_tested", {})
    for file_name, file_result in files_tested.items():
        success = file_result.get("success", False)
        converted_to = file_result.get("converted_to")

        # Create display name
        display_name = f"{file_name}"
        if converted_to:
            display_name += f" -> {converted_to}"

        # Create collapsible section with button
        toggle_button = pn.widgets.Button(
            name=display_name,
            button_type="primary" if success else "danger",
            sizing_mode="stretch_width",
        )

        # Create content section (initially visible)
        content_col = pn.Column(sizing_mode="stretch_width", visible=True)

        # Add conversion notice if applicable
        if converted_to:
            notice_pane = pn.pane.Markdown(
                f"**Field Conversion:** `{file_name}` -> `{converted_to}`\n\nThis field was renamed in schema v{schema_version}",
                styles={
                    "background": "#e3f2fd",
                    "border-left": f"4px solid {AIND_COLORS['light_blue']}",
                    "padding": "10px",
                    "margin": "10px 0",
                },
            )
            content_col.append(notice_pane)

        if success:
            # Side-by-side comparison
            v1_data = file_result.get("v1_data", {})
            v2_data = file_result.get("v2_data", {})

            # Ensure data is JSON serializable
            v1_json = json.loads(json.dumps(v1_data, default=str))
            v2_json = json.loads(json.dumps(v2_data, default=str))

            # CSS for JSON pane to handle long URLs
            json_pane_styles = {
                "overflow": "auto",
                "word-wrap": "break-word",
                "white-space": "pre-wrap",
            }

            comparison_row = pn.Row(
                pn.Column(
                    pn.pane.Markdown("### Original (v1)"),
                    pn.pane.JSON(
                        v1_json,
                        depth=2,
                        styles=json_pane_styles,
                        sizing_mode="stretch_width",
                    ),
                    styles=json_box_style,
                    sizing_mode="stretch_width",
                ),
                pn.Column(
                    pn.pane.Markdown("### Upgraded (v2)"),
                    pn.pane.JSON(
                        v2_json,
                        depth=2,
                        styles=json_pane_styles,
                        sizing_mode="stretch_width",
                    ),
                    styles=json_box_style,
                    sizing_mode="stretch_width",
                ),
                sizing_mode="stretch_width",
            )
            content_col.append(comparison_row)
        else:
            # Show error
            error_text = file_result.get("error", "Unknown error")
            error_pane = pn.pane.Markdown(
                f"**Upgrade Failed:**\n\n{error_text}",
                styles={
                    "background": "#fff5f5",
                    "border-left": f"4px solid {AIND_COLORS['red']}",
                    "padding": "10px",
                    "margin": "10px 0",
                },
            )
            content_col.append(error_pane)

            # Add collapsible traceback if available
            traceback_text = file_result.get("traceback")
            if traceback_text:
                traceback_button = pn.widgets.Button(
                    name="Show Error Details",
                    button_type="warning",
                    width=200,
                )
                traceback_col = pn.Column(
                    pn.pane.Markdown(
                        f"```\n{traceback_text}\n```",
                        styles={"background": "#f5f5f5", "padding": "10px"},
                    ),
                    visible=False,
                    sizing_mode="stretch_width",
                )

                def make_traceback_toggle(tb_col, tb_btn):
                    def toggle(event):
                        tb_col.visible = not tb_col.visible
                        tb_btn.name = (
                            "Hide Error Details"
                            if tb_col.visible
                            else "Show Error Details"
                        )

                    return toggle

                traceback_button.on_click(
                    make_traceback_toggle(traceback_col, traceback_button)
                )
                content_col.append(traceback_button)
                content_col.append(traceback_col)

            # Show original data
            v1_data = file_result.get("v1_data", {})
            v1_json = json.loads(json.dumps(v1_data, default=str))

            json_pane_styles = {
                "overflow": "auto",
                "word-wrap": "break-word",
                "white-space": "pre-wrap",
            }

            content_col.append(
                pn.Column(
                    pn.pane.Markdown("### Original Data (v1)"),
                    pn.pane.JSON(
                        v1_json,
                        depth=2,
                        styles=json_pane_styles,
                        sizing_mode="stretch_width",
                    ),
                    styles=json_box_style,
                    sizing_mode="stretch_width",
                )
            )

        # Toggle visibility callback
        def make_toggle_callback(content):
            def toggle(event):
                content.visible = not content.visible
                event.obj.button_type = (
                    "primary" if content.visible else "default"
                )

            return toggle

        toggle_button.on_click(make_toggle_callback(content_col))

        main_col.append(toggle_button)
        main_col.append(content_col)

    return main_col


def build_panel_app():
    table_col = pn.Column()
    button = pn.widgets.Button(name="Load Table", button_type="primary")

    summary_box = pn.pane.Markdown("", sizing_mode="stretch_width")

    text_input = pn.widgets.TextInput(
        name="",
        placeholder="Type _id or name here...",
        sizing_mode="stretch_width",
        min_width=300,
    )
    upgrade_button = pn.widgets.Button(
        name="Run Upgrade", button_type="success", width=130, disabled=True
    )
    copy_url_button = pn.widgets.Button(
        name="Copy Shareable URL",
        button_type="default",
        width=200,
        disabled=True,
    )
    output_box = pn.Column(sizing_mode="stretch_width")
    js_pane = pn.pane.HTML("", height=0, width=0)

    # Enable/disable upgrade button based on text input
    def update_upgrade_button(event):
        upgrade_button.disabled = not bool(text_input.value.strip())

    text_input.param.watch(update_upgrade_button, "value")

    # Sync text_input with URL parameter
    pn.state.location.sync(text_input, {"value": "asset_id"})

    # Auto-run upgrade if asset_id is in URL
    if text_input.value:
        upgrade_button.disabled = False
        results = run_upgrade(text_input.value)
        output_box[:] = [display_upgrade_results(results)]
        copy_url_button.disabled = False

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
        success_detail = (
            df.groupby(["project_name", "status"])
            .size()
            .reset_index(name="count")
        )
        chart = (
            alt.Chart(success_detail)
            .mark_bar()
            .encode(
                x=alt.X("project_name:N", sort="-y", title="Project Name"),
                y=alt.Y("count:Q", title="Count"),
                color=alt.Color("status:N", title="Status"),
                tooltip=["project_name:N", "status:N", "count:Q"],
            )
            .properties(
                width="container",
                height=500,
                title="Upgrade Status Breakdown by Project",
            )
            .interactive()
        )
        table_col[:] = [
            "# Metadata Upgrade Status Table",
            tab,
            pn.pane.Vega(chart, sizing_mode="stretch_width"),
        ]
        table_col.loading = False

    def run_upgrade_callback(event):
        record_id_or_name = text_input.value
        if not record_id_or_name:
            output_box[:] = [
                pn.pane.Markdown(
                    "**Error:** Please enter an asset ID or name."
                )
            ]
            return

        # Show loading state
        output_box.loading = True
        upgrade_button.disabled = True
        copy_url_button.disabled = True

        try:
            # Use detailed upgrade function
            results = run_upgrade(record_id_or_name)

            # Display results with side-by-side comparison
            output_box[:] = [display_upgrade_results(results)]

            # Enable copy URL button after successful upgrade
            copy_url_button.disabled = False
        finally:
            # Clear loading state
            output_box.loading = False
            upgrade_button.disabled = False

    def copy_url_callback(event):
        # Generate JavaScript to copy current URL to clipboard
        js_code = """
            var url = window.location.href;
            navigator.clipboard.writeText(url).then(function() {
                console.log('URL copied to clipboard');
            }, function(err) {
                console.error('Failed to copy URL: ', err);
            });
        """
        js_pane.object = ""
        js_pane.object = f"<script>{js_code}</script>"

    button.on_click(load_table)
    upgrade_button.on_click(run_upgrade_callback)
    copy_url_button.on_click(copy_url_callback)
    table_col.append(button)
    input_label = pn.pane.Markdown("**Enter _id or name:**")

    input_row = pn.Row(
        text_input,
        pn.Spacer(width=5),
        upgrade_button,
        pn.Spacer(width=5),
        copy_url_button,
        sizing_mode="stretch_width",
        align="center",
    )

    main_col = pn.Column(
        "# Metadata Upgrade Status Table",
        summary_box,
        table_col,
        input_label,
        input_row,
        output_box,
        js_pane,
        sizing_mode="stretch_width",
    )
    return main_col


app = build_panel_app()
app.servable(title="Upgrade Status")
