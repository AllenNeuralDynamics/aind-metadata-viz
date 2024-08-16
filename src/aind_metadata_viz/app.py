import panel as pn
# import param
import pandas as pd
import altair as alt

from io import StringIO

from aind_metadata_viz.docdb import get_all

pn.extension('vega')
pn.extension(design='material')

color_options = {
    "default": ["grey", "red"],
    "lemonade": ["yellow", "pink"]
}

colors = color_options[pn.state.location.query_params['color']] if 'color' in pn.state.location.query_params else color_options['default']

data_list = get_all()

# headers = ["_id", "name", "created", "location"]
expected_files = ["data_description", "acquisition", "procedures",
                  "subject", "instrument", "processing",
                  "rig", "session", "metadata"]


# class Settings(param.Parameterized):
#     selected_file = param.String(default=None)
#     selected_field = param.String(default=None)


# Deal with setting up settings -- check first if we need to pull from query string
# QUERYSTR_FILE = 'file'
# QUERYSTR_FIELD = 'field'
# settings = Settings()

# pn.state.location.sync(settings, {'selected_file': QUERYSTR_FILE,
#                                   'selected_field': QUERYSTR_FIELD})


def process_present(data_list, expected_fields):
    """Process a data JSON

    Parameters
    ----------
    data_list : _type_
        _description_
    expected_files : _type_
        _description_

    Returns
    -------
    _type_
        _description_
    """

    output = []
    
    for data in data_list:
        present = {}
        # For each data asset, check if the expected files are present or null
        for field in expected_fields:
            present[field] = not (data[field] == None) if field in data.keys() else False

        output.append(present)

    return output


def compute_count_true(df):
    """For each column, compute the count of true values

    Parameters
    ----------
    df : _type_
        _description_
    """
    sum_df = df.sum().to_frame(name='present')
    sum_df['absent'] = df.shape[0] - sum_df['present']

    return sum_df


def build_top():
    processed = process_present(data_list, expected_files)
    df = pd.DataFrame(processed, columns=expected_files)

    sum_df = compute_count_true(df)
    # convert to long form
    sum_longform_df = sum_df.reset_index().melt(id_vars='index', var_name='status', value_name='sum')

    chart = alt.Chart(sum_longform_df).mark_bar().encode(
        x=alt.X('index:N', title=None, axis=alt.Axis(grid=False)),
        y=alt.Y('sum:Q', title='Data assets', axis=alt.Axis(grid=False)),
        color=alt.Color('status:N', 
                        scale=alt.Scale(domain=['present', 'absent'],
                                        range=colors),
                        legend=None)
    ).properties(
        width=400
    )

    legend = alt.Chart(pd.DataFrame({
        'status': ['File present', 'File absent'],
        'color': colors,
        'x': [0, 0],
        'y': [15, 0]
    })).mark_text(
        align='left',
        dx=10
    ).encode(
        text=alt.Text('status:N'),
        color=alt.Color('color:N', scale=None),
        x=alt.value(410),  # Adjust position
        y=alt.Y('y:Q', scale=None)
    )
    return pn.panel(chart + legend)


def build_csv(file, field):
    id_fields = ['name', '_id', 'location', 'creation']

    df_data = []
    for data in data_list:
        if not data[file] is None:
            if mid_selector.value == ' ' or not field in data[file] or data[file][field] is None:
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
    csv_escaped = csv.replace('\n', '\\n').replace('"', '\\"')  # Escape newlines and double quotes

    if not mid_selector.value == ' ':
        filename = f'{top_selector.value}-{mid_selector.value}-missing.csv'
    else:
        filename = f'{top_selector.value}-missing.csv'

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
    # it's not clear why this extra clear is needed, but it's necessary for the download to work
    js_pane.object = ''
    js_pane.object = f'<script>{js_code}</script>'

top_selector = pn.widgets.Select(name='Select file:',
                                      options=expected_files)
pn.state.location.sync(top_selector, {'value': 'file'})

mid_selector = pn.widgets.Select(name='Sub-select for:',
                                      options=[])
pn.state.location.sync(mid_selector, {'value': 'field'})


download_button = pn.widgets.Button(name='Download')
download_button.on_click(build_csv_jscode)


def build_mid(selected):
    mid_list = []
    for data in data_list:
        if not data[selected]==None:
            mid_list.append(data[selected])

    processed = process_present(mid_list, mid_list[0].keys())
    df = pd.DataFrame(processed, columns=mid_list[0].keys())

    sum_df = compute_count_true(df)
    # convert to long form
    sum_longform_df = sum_df.reset_index().melt(id_vars='index', var_name='status', value_name='sum')

    chart = alt.Chart(sum_longform_df).mark_bar().encode(
        x=alt.X('index:N', title=None, axis=alt.Axis(grid=False)),
        y=alt.Y('sum:Q', title='Data assets', axis=alt.Axis(grid=False)),
        color=alt.Color('status:N', 
                        scale=alt.Scale(domain=['present', 'absent'],
                                        range=colors),
                        legend=None)
    ).properties(
        width=400
    )

    legend = alt.Chart(pd.DataFrame({
        'status': ['File present', 'File absent'],
        'color': colors,
        'x': [0, 0],
        'y': [15, 0]
    })).mark_text(
        align='left',
        dx=10
    ).encode(
        text=alt.Text('status:N'),
        color=alt.Color('color:N', scale=None),
        x=alt.value(410),  # Adjust position
        y=alt.Y('y:Q', scale=None)
    )

    # Also update the selected list
    option_list = [' '] + list(mid_list[0].keys())
    mid_selector.options = option_list

    return pn.panel(chart + legend)

    
top_plot = build_top()
mid_plot = pn.bind(build_mid, selected=top_selector)
# Setup the rows
top_row = pn.Row(top_plot)
second_row = pn.Row(top_selector, mid_plot)
bot_row = pn.Row(mid_selector, download_button)
# footer = pn.pane.JSON(data_list, width=400)

header = """
# Metadata viewer

This app steps through all of the metadata stored in DocDB and checks
whether every dictionary key is present or absent (null)
"""

header_pane = pn.pane.Markdown(header)

# Put everything in a column and buffer it
main_col = pn.Column(header_pane, top_row, second_row, bot_row)
pn.Row(pn.layout.HSpacer(), main_col, pn.layout.HSpacer()).servable()
