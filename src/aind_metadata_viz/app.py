import panel as pn
import altair as alt
from aind_metadata_viz import docdb

pn.extension(design="material")
pn.extension("vega")
alt.themes.enable("ggplot2")

color_options = {"default": ["grey", "red"], "lemonade": ["#FFEF00", "pink"]}

colors = (
    color_options[pn.state.location.query_params["color"]]
    if "color" in pn.state.location.query_params
    else color_options["default"]
)

db = docdb.Database()

modality_selector = pn.widgets.Select(
    name="Select modality:", options=["all"] + docdb.MODALITIES
)

top_selector = pn.widgets.Select(
    name="Select metadata file:", options=docdb.EXPECTED_FILES
)

mid_selector = pn.widgets.Select(name="Sub-select for field:", options=[])

missing_selector = pn.widgets.Select(
    name="Value state", options=["Missing", "Present"]
)

derived_switch = pn.widgets.Switch.from_param(db.param.derived_filter)

pn.state.location.sync(modality_selector, {"value": "modality"})
pn.state.location.sync(top_selector, {"value": "file"})
pn.state.location.sync(mid_selector, {"value": "field"})
pn.state.location.sync(missing_selector, {"value": "missing"})


def file_present_chart():
    sum_longform_df = db.get_file_presence()

    chart = (
        alt.Chart(sum_longform_df)
        .mark_bar()
        .encode(
            x=alt.X("index:N", title=None, axis=alt.Axis(grid=False)),
            y=alt.Y(
                "sum:Q",
                title="Metadata assets (n)",
                axis=alt.Axis(grid=False),
            ),
            color=alt.Color(
                "status:N",
                scale=alt.Scale(domain=["present", "absent"], range=colors),
                legend=None,
            ),
        )
        .properties(title="Metadata files")
    )

    pane = pn.pane.Vega(chart)

    return pane


def notfile_present_chart():
    # sum_longform_df = db.get_field_presence()

    # chart = (
    #     alt.Chart(sum_longform_df)
    #     .mark_bar()
    #     .encode(
    #         x=alt.X("index:N", title=None, axis=alt.Axis(grid=False)),
    #         y=alt.Y(
    #             "sum:Q",
    #             title=None,
    #             axis=alt.Axis(grid=False),
    #         ),
    #         color=alt.Color(
    #             "status:N",
    #             scale=alt.Scale(domain=["present", "absent"], range=colors),
    #             legend=None,
    #         ),
    #     )
    #     .properties(title="Other fields")
    # )

    # pane = pn.pane.Vega(chart)

    pane = pn.pane.Markdown("# todo2") 

    return pane


js_pane = pn.pane.HTML("", height=0, width=0).servable()


def build_csv_jscode(event):
    """
    Create the javascript code and append it to the page.
    """
    csv = db.get_csv(
        top_selector.value, mid_selector.value, missing_selector.value
    )
    csv_escaped = csv.replace("\n", "\\n").replace(
        '"', '\\"'
    )  # Escape newlines and double quotes

    get_missing = missing_selector.value == "Missing"
    missing_text = "missing" if get_missing else "present"

    if not mid_selector.value == " ":
        filename = (
            f"{top_selector.value}-{mid_selector.value}-{missing_text}.csv"
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


def build_mid(selected_file, **args):
    """ """
    db.set_file(selected_file)

    sum_longform_df = db.get_file_field_presence()

    chart = (
        alt.Chart(sum_longform_df)
        .mark_bar()
        .encode(
            x=alt.X("index:N", title=None, axis=alt.Axis(grid=False)),
            y=alt.Y(
                "sum:Q", title="Metadata assets (n)", axis=alt.Axis(grid=False)
            ),
            color=alt.Color(
                "status:N",
                scale=alt.Scale(domain=["present", "absent"], range=colors),
                legend=None,
            ),
        )
        .properties(title=f"Fields in {db.file} file")
    )

    # Also update the selected list
    if len(db.mid_list) > 0:
        option_list = [" "] + list(db.mid_list[0].keys())
    else:
        option_list = []

    mid_selector.options = option_list

    return pn.pane.Vega(chart)


header = f"""
# Missing metadata viewer

This app steps through all of the metadata stored in DocDB and checks whether every dictionary key's value is <span style="color:{colors[0]}">present</span> or <span style="color:{colors[1]}">missing</span>
"""

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
    pn.Row("Filter for derived assets:", derived_switch),
    download_pane,
    mid_selector,
    missing_selector,
    download_button,
    width=400,
)


def build_row(selected_modality, derived_filter):
    db.modality_filter = selected_modality

    return pn.Row(file_present_chart, notfile_present_chart)


top_row = pn.bind(build_row,
                  selected_modality=modality_selector,
                  derived_filter=derived_switch)

mid_plot = pn.bind(
    build_mid,
    selected_file=top_selector,
    selected_modality=modality_selector,
    derived_filter=derived_switch
)

# Put everything in a column and buffer it
main_col = pn.Column(top_row, mid_plot, sizing_mode="stretch_width")

pn.Row(left_col, main_col, pn.layout.HSpacer()).servable(title="Metadata Viz")
