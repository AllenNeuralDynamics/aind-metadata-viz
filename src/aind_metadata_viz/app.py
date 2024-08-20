import panel as pn

# import param
import pandas as pd
import altair as alt

from io import StringIO

from aind_metadata_viz.docdb import get_all
from aind_metadata_viz.metadata_helpers import (
    process_present_list,
    check_present,
)

pn.extension(design="material")
pn.extension("vega")
alt.themes.enable("ggplot2")

color_options = {"default": ["grey", "red"], "lemonade": ["yellow", "pink"]}

colors = (
    color_options[pn.state.location.query_params["color"]]
    if "color" in pn.state.location.query_params
    else color_options["default"]
)

data_list = get_all()

# headers = ["_id", "name", "created", "location"]
expected_files = [
    "data_description",
    "acquisition",
    "procedures",
    "subject",
    "instrument",
    "processing",
    "rig",
    "session",
    "metadata",
]


# class Settings(param.Parameterized):
#     selected_file = param.String(default=None)
#     selected_field = param.String(default=None)


# Deal with setting up settings -- check first if we need to pull from
# query string
# QUERYSTR_FILE = 'file'
# QUERYSTR_FIELD = 'field'
# settings = Settings()

# pn.state.location.sync(settings, {'selected_file': QUERYSTR_FILE,
#                                   'selected_field': QUERYSTR_FIELD})


def compute_count_true(df):
    """For each column, compute the count of true values

    Parameters
    ----------
    df : _type_
        _description_
    """
    sum_df = df.sum().to_frame(name="present")
    sum_df["absent"] = df.shape[0] - sum_df["present"]

    return sum_df


def build_top():
    processed = process_present_list(data_list, expected_files)
    df = pd.DataFrame(processed, columns=expected_files)

    sum_df = compute_count_true(df)
    # convert to long form
    sum_longform_df = sum_df.reset_index().melt(
        id_vars="index", var_name="status", value_name="sum"
    )

    chart = (
        alt.Chart(sum_longform_df)
        .mark_bar()
        .encode(
            x=alt.X("index:N", title=None, axis=alt.Axis(grid=False)),
            y=alt.Y(
                "sum:Q",
                title="Metadata assets (count)",
                axis=alt.Axis(grid=False),
            ),
            color=alt.Color(
                "status:N",
                scale=alt.Scale(domain=["present", "absent"], range=colors),
                legend=None,
            ),
        )
    )

    pane = pn.pane.Vega(chart)

    return pane


def build_csv(file, field):
    # For everybody who is missing the currently active file/field
    id_fields = ["name", "_id", "location", "creation"]

    df_data = []
    for data in data_list:
        if not data[file] is None:
            if mid_selector.value == " " or check_present(field, data[file]):
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


js_pane = pn.pane.HTML("", height=0, width=0).servable()


def build_csv_jscode(event):
    csv = build_csv(top_selector.value, mid_selector.value)
    csv_escaped = csv.replace("\n", "\\n").replace(
        '"', '\\"'
    )  # Escape newlines and double quotes

    if not mid_selector.value == " ":
        filename = f"{top_selector.value}-{mid_selector.value}-missing.csv"
    else:
        filename = f"{top_selector.value}-missing.csv"

    js_code = f"""
console.log('here');
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


top_selector = pn.widgets.Select(
    name="Select metadata file:", options=expected_files
)
pn.state.location.sync(top_selector, {"value": "file"})

mid_selector = pn.widgets.Select(name="Sub-select for field:", options=[])
pn.state.location.sync(mid_selector, {"value": "field"})


download_button = pn.widgets.Button(name="Download")
download_button.on_click(build_csv_jscode)


def build_mid(selected):
    mid_list = []
    for data in data_list:
        if data[selected] is not None:
            mid_list.append(data[selected])

    processed = process_present_list(mid_list, mid_list[0].keys())
    df = pd.DataFrame(processed, columns=mid_list[0].keys())

    sum_df = compute_count_true(df)
    # convert to long form
    sum_longform_df = sum_df.reset_index().melt(
        id_vars="index", var_name="status", value_name="sum"
    )

    chart = (
        alt.Chart(sum_longform_df)
        .mark_bar()
        .encode(
            x=alt.X("index:N", title=None, axis=alt.Axis(grid=False)),
            y=alt.Y("sum:Q", title="Data assets", axis=alt.Axis(grid=False)),
            color=alt.Color(
                "status:N",
                scale=alt.Scale(domain=["present", "absent"], range=colors),
                legend=None,
            ),
        )
    )

    # Also update the selected list
    option_list = [" "] + list(mid_list[0].keys())
    mid_selector.options = option_list

    return pn.panel(chart)


header = """
# Missing metadata viewer

This app steps through all of the metadata stored in DocDB and checks whether every dictionary key's value is <span style="color:grey">present</span> or <span style="color:red">missing</span>
"""

header_pane = pn.pane.Markdown(header)

# Left column (controls)
left_col = pn.Column(
    header_pane, top_selector, mid_selector, download_button, width=400
)

mid_plot = pn.bind(build_mid, selected=top_selector)

# Put everything in a column and buffer it
main_col = pn.Column(build_top, mid_plot, sizing_mode="stretch_width")

pn.Row(left_col, main_col, pn.layout.HSpacer()).servable()
