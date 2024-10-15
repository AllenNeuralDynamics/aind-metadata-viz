import panel as pn
import altair as alt
import pandas as pd
from aind_metadata_viz import docdb
from aind_metadata_viz.docdb import _get_all
from aind_data_schema import __version__ as ads_version

_get_all(test_mode=True)

pn.extension(design="material")
pn.extension("vega")
alt.themes.enable("ggplot2")

AIND_COLORS = colors = {
    "dark_blue": "#003057",
    "light_blue": "#2A7DE1",
    "green": "#1D8649",
    "yellow": "#FFB71B",
    "grey": "#7C7C7F",
    "red": "#FF5733",
}

# Define CSS to set the background color
background_color = AIND_COLORS[pn.state.location.query_params["background"] if "background" in pn.state.location.query_params else "dark_blue"]
css = f"""
body {{
    background-color: {background_color} !important;
    background-image: url('/images/background.svg') !important;
}}
"""

# Add the custom CSS
pn.config.raw_css.append(css)

color_options = {
    "default": {
        "valid": AIND_COLORS["green"],
        "present": AIND_COLORS["light_blue"],
        "optional": "grey",
        "missing": "red",
        "excluded": "#F0F0F0",
    },
    "lemonade": {
        "valid": "#F49FD7",
        "present": "#FFD966",
        "optional": "grey",
        "missing": "#9FF2F5",
        "excluded": "white",
    },
    "aind": {
        "valid": AIND_COLORS["green"],
        "present": AIND_COLORS["light_blue"],
        "optional": AIND_COLORS["grey"],
        "missing": AIND_COLORS["red"],
        "excluded": "white",
    }
}

colors = (
    color_options[pn.state.location.query_params["colors"]]
    if "colors" in pn.state.location.query_params
    else color_options["default"]
)
color_list = list(colors.values())

db = docdb.Database()

modality_selector = pn.widgets.Select(
    name="Filter by modality:", options=["all"] + docdb.MODALITIES
)

top_selector = pn.widgets.Select(
    name="Filter by core file:", options=docdb.ALL_FILES
)

field_selector = pn.widgets.Select(name="Filter download by field:", options=[])

missing_selector = pn.widgets.Select(
    name="Filter download by state", options=["Not Valid/Present", "Valid/Present"]
)
missing_selector.value = "Not Valid/Present"

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


def file_present_chart():
    """Build a chart of presence split by core metadata file type"""
    sum_longform_df = db.get_file_presence()
    local_states = sum_longform_df["state"].unique()
    local_color_list = [colors[state] for state in local_states]

    file_selection = alt.selection_point(fields=['file'], empty='none', name='file', value=top_selector.value)

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
        .add_params(file_selection)
        .properties(title="Metadata files")
    )

    pane = pn.pane.Vega(chart)

    def update_selection(event):
        if len(event.new) > 0:
            top_selector.value = event.new[0]['file']
    pane.selection.param.watch(update_selection, 'file')

    return pane


def modality_present_chart():
    """Build a chart of presence split by modality"""

    df = pd.DataFrame()
    for modality in docdb.MODALITIES:
        sum_longform_df = db.get_modality_presence(modality=modality)
        df = pd.concat([df, sum_longform_df])

    modality_selection = alt.selection_point(fields=['modality'], empty='all', name='modality', value=(modality_selector.value if modality_selector.value != "all" else None))

    chart = (
        alt.Chart(df)
        .mark_bar()
        .encode(
            x=alt.X("modality:N", title=None, axis=alt.Axis(grid=False)),
            y=alt.Y(
                "sum:Q",
                title="State (%)",
                axis=alt.Axis(
                    grid=False,
                    values=[0, 0.25, 0.5, 0.75, 1],
                    labelExpr="datum.value * 100 + '%'",
                ),
            ),
            color=alt.Color(
                "state:N",
                scale=alt.Scale(
                    domain=list(colors.keys()),
                    range=color_list,
                ),
                legend=None,
            ),
            opacity=alt.condition(
                modality_selection,
                alt.value(1),
                alt.value(0.2),
            ),
        )
        .add_params(modality_selection)
        .properties(title="File state by modality")
    )

    pane = pn.pane.Vega(chart)

    def update_selection(event):
        if len(event.new) > 0:
            modality_selector.value = event.new[0]['modality']
        else:
            modality_selector.value = "all"
    pane.selection.param.watch(update_selection, 'modality')

    return pane


js_pane = pn.pane.HTML("", height=0, width=0).servable()


def build_csv_jscode(event):
    """
    Create the javascript code and append it to the page.
    """
    csv = db.get_csv(missing_selector.value)
    csv_escaped = csv.replace("\n", "\\n").replace(
        '"', '\\"'
    )  # Escape newlines and double quotes

    get_missing = missing_selector.value == "Not Valid/Present"
    missing_text = "bad" if get_missing else "good"

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
    f"{hd_style('present')} but invalid, {hd_style('optional')}, "
    f"{hd_style('missing')}, or "
    f"{hd_style('excluded')} for the record's modality."
)

download_md = """
**Download options**
"""

outer_style = {
    'background': '#ffffff',
    'border-radius': '5px',
    'border': '2px solid black',
    'padding': '10px',
    'box-shadow': '5px 5px 5px #bcbcbc',
    'margin': "5px",
}


header_pane = pn.pane.Markdown(header, styles=outer_style, width=420)
download_pane = pn.pane.Markdown(download_md)

control_col = pn.Column(
    modality_selector,
    top_selector,
    derived_selector,
    download_pane,
    field_selector,
    missing_selector,
    download_button,
    styles=outer_style,
    width=420,
)

# Left column (controls)
left_col = pn.Column(
    header_pane,
    control_col,
    width=420,
)


def build_row(selected_modality, derived_filter):
    db.modality_filter = selected_modality
    db.derived_filter = derived_filter

    return pn.Row(file_present_chart, modality_present_chart) 


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
main_col = pn.Column(top_row, mid_plot, styles=outer_style, width=515)

pn.Row(pn.HSpacer(), left_col, pn.Spacer(width=20), main_col, pn.HSpacer(), margin=20).servable(
    title="Metadata Portal",
)
