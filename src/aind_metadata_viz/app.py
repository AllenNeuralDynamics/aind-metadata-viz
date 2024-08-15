import panel as pn
import pandas as pd
import altair as alt

from aind_metadata_viz.docdb import get_all

pn.extension('vega')
pn.extension(design='material')

data_list = get_all()

# headers = ["_id", "name", "created", "location"]
expected_files = ["data_description", "acquisition", "procedures",
                  "subject", "instrument", "processing",
                  "rig", "session", "metadata"]


def process_present(data_list, expected_files):
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
        for expected_file in expected_files:
            present[expected_file] = not (data[expected_file] == None) if expected_file in data.keys() else False

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


processed = process_present(data_list, expected_files)
df = pd.DataFrame(processed, columns=expected_files)

sum_df = compute_count_true(df)
# convert to long form
sum_longform_df = sum_df.reset_index().melt(id_vars='index', var_name='status', value_name='sum')

chart = alt.Chart(sum_longform_df).mark_bar().encode(
    x=alt.X('index:N', title=None),
    y=alt.Y('sum:Q', title='Data assets'),
    color=alt.Color('status:N', 
                    scale=alt.Scale(domain=['present', 'absent'],
                                    range=['grey', 'red']),
                    legend=None)
)

legend = alt.Chart(pd.DataFrame({
    'status': ['present', 'absent'],
    'color': ['grey', 'red'],
    'x': [0, 0],
    'y': [15, 0]
})).mark_text(
    align='left',
    dx=10
).encode(
    text=alt.Text('status:N'),
    color=alt.Color('color:N', scale=None),
    x=alt.value(185),  # Adjust position
    y=alt.Y('y:Q', scale=None)
)

top_plot = pn.panel(chart + legend)
top_selector = pn.widgets.MultiChoice(name='Select file:',
    options=expected_files)

pn.Row(top_plot, top_selector).servable()

pn.pane.JSON(data_list).servable()
