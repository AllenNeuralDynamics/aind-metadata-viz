import altair as alt
import panel as pn
from aind_data_schema import __version__ as ads_version
from aind_metadata_viz import database
from aind_metadata_viz.utils import AIND_COLORS, COLOR_OPTIONS, hd_style, outer_style
from aind_metadata_viz.charts import file_present_chart, modality_present_chart

pn.extension("vega", design="material")
alt.themes.enable("ggplot2")

# Define CSS to set the background color and add to panel
background_param = pn.state.location.query_params.get("background", "dark_blue")
background_color = AIND_COLORS.get(background_param, AIND_COLORS["dark_blue"])

css = f"""
body {{
    background-color: {background_color} !important;
    background-image: url('/images/aind-pattern.svg') !important;
    background-size: 60%;
}}
"""
pn.config.raw_css.append(css)

# Get the active color list
colors = (
    COLOR_OPTIONS.get(pn.state.location.query_params.get("colors"), COLOR_OPTIONS["default"])
)
color_list = list(colors.values())

# Load the database
db = database.Database()

# Set up selectors and sync with URL
modality_selector = pn.widgets.Select(
    name="Filter by modality:", options=["all"] + database.MODALITIES
)

top_selector = pn.widgets.Select(
    name="Filter by core file:", options=database.ALL_FILES
)

field_selector = pn.widgets.Select(name="Filter download by field:", options=[])

missing_selector = pn.widgets.Select(
    name="Filter download by state", options=["Missing", "Valid/Present"]
)
missing_selector.value = "Missing"

derived_selector = pn.widgets.Select(
    name="Filter by history:",
    options=["All assets", "Raw", "Derived"],
)
derived_selector.value = "All assets"

pn.state.location.sync(modality_selector, {"value": "modality"})
pn.state.location.sync(top_selector, {"value": "file"})
pn.state.location.sync(field_selector, {"value": "field"})
pn.state.location.sync(missing_selector, {"value": "missing"})
pn.state.location.sync(derived_selector, {"value": "derived"})


# Chart definitions


js_pane = pn.pane.HTML("", height=0, width=0).servable()


def build_csv_jscode(event):
    """
    Create the javascript code and append it to the page.
    """
    csv = db.get_csv(missing_selector.value)
    csv_escaped = csv.replace("\n", "\\n").replace(
        '"', '\\"'
    )  # Escape newlines and double quotes

    missing_text = "bad" if missing_selector.value == "Missing" else "good"

    if not field_selector.value == " ":
        filename = (
            f"{top_selector.value}-{field_selector.value}-{missing_text}.csv"
        )
    else:
        filename = f"{top_selector.value}-{missing_text}.csv"

    js_code = f"""
var text = "{csv_escaped}";
var blob = new Blob([text], {{ type: 'text/plain' }});

var url = window.URL.createObjectURL(blob);

var a = document.createElement('a');
a.href = url;
a.download = "{filename}";

document.body.appendChild(a);

a.click();

document.body.removeChild(a);

window.URL.revokeObjectURL(url);
"""
    # it's not clear why this extra clear is needed, but it's
    #  necessary for the download to work
    js_pane.object = ""
    js_pane.object = f"<script>{js_code}</script>"


csv_download_button = pn.widgets.Button(name="Download")
csv_download_button.on_click(build_csv_jscode)


def field_present_chart(selected_file, derived_filter, **args):
    """ """
    db.set_file(selected_file)
    db.derived_filter = derived_filter

    sum_longform_df = db.get_file_field_presence()

    field_selection = alt.selection_point(fields=['field'], empty='none', name='field', value=field_selector.value)

    chart = (
        alt.Chart(sum_longform_df)
        .mark_bar()
        .encode(
            x=alt.X("field:N", title=None, axis=alt.Axis(grid=False)),
            y=alt.Y(
                "sum:Q",
                title="Metadata assets (n)",
                axis=alt.Axis(grid=False),
            ),
            color=alt.Color(
                "state:N",
                scale=alt.Scale(
                    domain=list(colors.keys()),
                    range=color_list,
                ),
                legend=None,
            ),
        )
        .add_params(field_selection)
        .properties(title=f"Fields in {db.file} file")
    )

    # Also update the selected list
    option_list = [" "] + db.field_list

    field_selector.options = option_list
    pane = pn.pane.Vega(chart)

    def update_selection(event):
        if len(event.new) > 0:
            field_selector.value = event.new[0]['field']
    pane.selection.param.watch(update_selection, 'field')

    return pane




header = (
    f"# Metadata Portal\n\n"
    "This app steps through all of the metadata stored in DocDB and determines whether every record's fields "
    "(and subfields) are "
    f"{hd_style('valid', colors)} for aind-data-schema v{ads_version}, "
    f"{hd_style('present', colors)} but invalid, {hd_style('optional', colors)}, "
    f"{hd_style('missing', colors)}, or "
    f"{hd_style('excluded', colors)} for the record's modality."
)

download_md = """
**Download options**
The download button creates a CSV file with information about the metadata records that match the filter settings.
"""



header_pane = pn.pane.Markdown(header, styles=outer_style, width=420)

total_md = f"<p style=\"text-align:center\"><b>{db.get_overall_valid():1.2f}%</b> of all metadata records are fully {hd_style('valid', colors)}</p>"

percent_total = pn.pane.Markdown(total_md, styles=outer_style, width=420)

download_pane = pn.pane.Markdown(download_md)

control_col = pn.Column(
    modality_selector,
    top_selector,
    derived_selector,
    download_pane,
    field_selector,
    missing_selector,
    csv_download_button,
    styles=outer_style,
    width=420,
)

# Left column (controls)
left_col = pn.Column(
    header_pane,
    percent_total,
    control_col,
    width=420,
)


def build_row(selected_modality, derived_filter):
    db.modality_filter = selected_modality
    db.derived_filter = derived_filter

    return pn.Row(file_present_chart(db, colors, top_selector), modality_present_chart(db, colors, color_list, modality_selector))


top_row = pn.bind(
    build_row,
    selected_modality=modality_selector,
    derived_filter=derived_selector,
)

mid_plot = pn.bind(
    field_present_chart,
    selected_file=top_selector,
    selected_modality=modality_selector,
    derived_filter=derived_selector,
)

# Put everything in a column and buffer it
main_col = pn.Column(top_row, mid_plot, styles=outer_style, width=515)

main_row = pn.Row(pn.HSpacer(), left_col, pn.Spacer(width=20), main_col, pn.HSpacer(), margin=20)

# Add the validator search section
validator_name_selector = pn.widgets.TextInput(name="Enter asset name to validate:", value="", placeholder="Asset name", width=800)
pn.state.location.sync(validator_name_selector, {"value": "validator_name"})

validator = database.RecordValidator(validator_name_selector.value, colors)


def build_validator(validator_name):
    validator.update(validator_name)
    col = pn.Column(validator_name_selector, validator.panel(), width=(515+20+420), styles=outer_style)
    row = pn.Row(pn.HSpacer(), col, pn.HSpacer())
    return row


validator_row = pn.bind(build_validator,
                        validator_name=validator_name_selector)

pn.Column(main_row, validator_row).servable(
    title="Metadata Portal",
)
