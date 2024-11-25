import panel as pn
import altair as alt
import pandas as pd

import aind_metadata_viz.database as database


def file_present_chart(db, colors, selector):
    """Build a chart of presence split by core metadata file type"""
    sum_longform_df = db.get_file_presence()
    local_states = sum_longform_df["state"].unique()
    local_color_list = [colors[state] for state in local_states]

    file_selection = alt.selection_point(fields=['file'], empty='none', name='file', value=selector.value)

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
            selector.value = event.new[0]['file']
    pane.selection.param.watch(update_selection, 'file')

    return pane


def modality_present_chart(db, colors, color_list, selector):
    """Build a chart of presence split by modality"""

    df_list = []
    for modality in database.MODALITIES:
        sum_longform_df = db.get_modality_presence(modality=modality)
        df_list.append(sum_longform_df)
    df = pd.concat(df_list)

    modality_selection = alt.selection_point(fields=['modality'], empty='all', name='modality', value=(selector.value if selector.value != "all" else None))

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
            selector.value = event.new[0]['modality']
        else:
            selector.value = "all"
    pane.selection.param.watch(update_selection, 'modality')

    return pane