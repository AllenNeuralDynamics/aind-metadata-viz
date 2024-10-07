import panel as pn
import altair as alt
from aind_metadata_viz import docdb
from aind_metadata_viz.docdb import _get_all
from aind_data_schema import __version__ as ads_version

_get_all(test_mode=True)

pn.extension(design="material")
pn.extension("vega")
alt.themes.enable("ggplot2")

color_options = {
    "default": {
        "valid": "green",
        "present": "grey",
        "optional": "grey",
        "missing": "red",
        "excluded": "white",
    },
    "lemonade": {
        "valid": "#9FF2F5",
        "optional": "#F49FD7",
        "optional": "grey",
        "missing": "#F49FD7",
        "excluded": "white",
    },
}

colors = (
    color_options[pn.state.location.query_params["color"]]
    if "color" in pn.state.location.query_params
    else color_options["default"]
)
color_list = list(colors.values())

db = docdb.Database()

modality_selector = pn.widgets.Select(
    name="Select modality:", options=["all"] + docdb.MODALITIES
)

top_selector = pn.widgets.Select(
    name="Select metadata file:", options=docdb.ALL_FILES
)

field_selector = pn.widgets.Select(name="Sub-select for field:", options=[])

missing_selector = pn.widgets.Select(
    name="Value state", options=["Missing", "Present"]
)

derived_selector = pn.widgets.Select(
    name="Filter for:",
    options=["All assets", "Raw", "Derived"],
)
derived_selector.value = "All assets"

pn.state.location.sync(modality_selector, {"value": "modality"})
pn.state.location.sync(top_selector, {"value": "file"})
pn.state.location.sync(field_selector, {"value": "field"})
pn.state.location.sync(missing_selector, {"value": "missing"})
pn.state.location.sync(derived_selector, {"value": "derived"})


def file_present_chart():
    sum_longform_df = db.get_file_presence()
    # print(sum_longform_df)
    local_states = sum_longform_df["state"].unique()
    local_color_list = [colors[state] for state in local_states]

    chart = (
        alt.Chart(sum_longform_df)
        .mark_bar()
        .encode(
            x=alt.X("file:N", title=None, axis=alt.Axis(grid=False)),
            y=alt.Y(
                "sum:Q",
                title="Metadata assets (n)",
                axis=alt.Axis(grid=False),
            ),
            color=alt.Color(
                "state:N",
                scale=alt.Scale(
                    domain=local_states,
                    range=local_color_list,
                ),
                legend=None,
            ),
        )
        .properties(title="Metadata files")
    )

    pane = pn.pane.Vega(chart)

    return pane


def notfile_present_chart():
    sum_longform_df = db.get_field_presence()

    chart = (
        alt.Chart(sum_longform_df)
        .mark_bar()
        .encode(
            x=alt.X("column:N", title=None, axis=alt.Axis(grid=False)),
            y=alt.Y(
                "count:Q",
                title=None,
                axis=alt.Axis(grid=False),
            ),
            color=alt.Color(
                "category:N",
                scale=alt.Scale(
                    domain=["valid", "present", "missing", "excluded"],
                    range=color_list,
                ),
                legend=None,
            ),
        )
        .properties(title="Other fields")
    )

    pane = pn.pane.Vega(chart)

    return pane


js_pane = pn.pane.HTML("", height=0, width=0).servable()


def build_csv_jscode(event):
    """
    Create the javascript code and append it to the page.
    """
    csv = db.get_csv(
        top_selector.value, field_selector.value, missing_selector.value
    )
    csv_escaped = csv.replace("\n", "\\n").replace(
        '"', '\\"'
    )  # Escape newlines and double quotes

    get_missing = missing_selector.value == "Missing"
    missing_text = "missing" if get_missing else "present"

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


download_button = pn.widgets.Button(name="Download")
download_button.on_click(build_csv_jscode)


def build_mid(selected_file, derived_filter, **args):
    """ """
    db.set_file(selected_file)
    db.derived_filter = derived_filter

    sum_longform_df = db.get_file_field_presence()

    chart = (
        alt.Chart(sum_longform_df)
        .mark_bar()
        .encode(
            x=alt.X("column:N", title=None, axis=alt.Axis(grid=False)),
            y=alt.Y(
                "count:Q",
                title="Metadata assets (n)",
                axis=alt.Axis(grid=False),
            ),
            color=alt.Color(
                "category:N",
                scale=alt.Scale(
                    domain=["valid", "present", "missing", "excluded"],
                    range=color_list,
                ),
                legend=None,
            ),
        )
        .properties(title=f"Fields in {db.file} file")
    )

    # Also update the selected list
    option_list = [" "] + db.field_list

    field_selector.options = option_list

    return pn.pane.Vega(chart)


def hd_style(text):
    return (
        f"<span style='font-weight: bold; color:{colors[text]}'>{text}</span>"
    )


header = (
    f"# Metadata Portal\n\n"
    "This app steps through all of the metadata stored in DocDB and determines whether every record's fields "
    "(and subfields) are "
    f"{hd_style('valid')} for aind-data-schema v{ads_version}, "
    f"{hd_style('present')} but invalid or {hd_style('optional')}, "
    f"{hd_style('missing')}, or "
    f"{hd_style('excluded')} for the record's modality."
)

download_md = """
**Download options**
"""

header_pane = pn.pane.Markdown(header)
download_pane = pn.pane.Markdown(download_md)

# Left column (controls)
left_col = pn.Column(
    header_pane,
    modality_selector,
    top_selector,
    derived_selector,
    download_pane,
    field_selector,
    missing_selector,
    download_button,
    width=400,
)


def build_row(selected_modality, derived_filter):
    db.modality_filter = selected_modality
    db.derived_filter = derived_filter

    return pn.Row(file_present_chart, notfile_present_chart)


top_row = pn.bind(
    build_row,
    selected_modality=modality_selector,
    derived_filter=derived_selector,
)

mid_plot = pn.bind(
    build_mid,
    selected_file=top_selector,
    selected_modality=modality_selector,
    derived_filter=derived_selector,
)

# Put everything in a column and buffer it
main_col = pn.Column(top_row, mid_plot, sizing_mode="stretch_width")

pn.Row(left_col, main_col, pn.layout.HSpacer()).servable(
    title="Metadata Portal"
)
