"""App for generating metadata queries"""

import pandas as pd
import panel as pn
import param

from aind_metadata_viz.utils import outer_style, AIND_COLORS, FIXED_WIDTH
from aind_metadata_viz.query.simple_query import QueryBuilder
from aind_metadata_viz.query.chat_query import ComplexQueryBuilder
from aind_metadata_viz.query.viewer import QueryViewer
from aind_metadata_viz.query.database import get_docdb_records


background_param = pn.state.location.query_params.get(
    "background", "dark_blue"
)
background_color = AIND_COLORS.get(background_param, AIND_COLORS["dark_blue"])

css = f"""
body {{
    background-color: {background_color} !important;
    background-image: url('/images/aind-pattern.svg') !important;
    background-size: 60%;
}}
"""
pn.config.raw_css.append(css)


class Settings(param.Parameterized):
    """Class for displaying all queries"""

    queries = param.List(default=[], allow_None=False)
    use_chat = param.Boolean(default=False)

    def __init__(self, **params):
        super().__init__(**params)

    def update(self, event):
        """Add new queries to the list"""
        self.queries = self.queries + event.new


settings = Settings()
pn.state.location.sync(
    settings,
    {
        "queries": "queries",
        "use_chat": "use_chat",
    },
)


class QueryResult(param.Parameterized):
    """Class for displaying query results"""

    query = param.Dict(default={})
    result = param.DataFrame(default=pd.DataFrame())

    def __init__(self, query, **params):
        super().__init__(**params)

        self.query_viewer = QueryViewer(query)
        self.result_pane = pn.pane.DataFrame(
            escape=False,
            index=False,
        )

        self.query_name = "Empty"

        self.update_query(query)

    def update_query(self, query: dict):
        """Update the query and fetch results"""

        if query:
            local_query = query.copy()
            self.query_name = local_query["_name"]
            del local_query["_name"]

            self.query_viewer.update(local_query)
            self.result_pane.object = None
            self.query_result = get_docdb_records(local_query)

            df = pd.DataFrame(self.query_result)

            # Rename name to Name
            if "name" in df.columns:
                df.rename(columns={"name": "Name"}, inplace=True)

            # Add a column that generates a link to the view app
            df["View Record"] = [
                f'<a href="/view?name={record["name"]}" target="_blank">View</a>'
                for record in self.query_result
            ]
            # Remove _id column
            if "_id" in df.columns:
                df.drop(columns=["_id"], inplace=True)

            self.result_pane.object = df

    def panel(self):
        """Return the query result panel"""
        return pn.Column(
            self.query_viewer.panel(),
            self.result_pane,
            width=FIXED_WIDTH - 50,
            name=self.query_name,
        )


query_builder = QueryBuilder()

saved_subject_ids = pn.state.location.query_params.get("subject_ids", [])
saved_modalities = pn.state.location.query_params.get("modalities", [])
saved_session_types = pn.state.location.query_params.get("session_types", [])
pn.state.location.sync(
    query_builder,
    {
        "project_name": "project_name",
        "subject_ids": "subject_ids",
        "modalities": "modalities",
        "session_types": "session_types",
    },
)

query_tabs = pn.Tabs(width=FIXED_WIDTH - 50)

# RUN INITIAL UPDATES

query_builder.project_name_selector.value = query_builder.project_name
query_builder.update_query_panel()
query_builder.update_subject_id_options()
query_builder.update_modality_options()
query_builder.update_session_type_options()
query_builder.subject_id_selector.value = saved_subject_ids
query_builder.modality_selector.value = saved_modalities
query_builder.session_type_selector.value = saved_session_types

# CHAT BUILDER

chat_builder = ComplexQueryBuilder()

# FULL QUERY LIST


query_builder.param.watch(
    settings.update,
    "queries",
)
chat_builder.param.watch(
    settings.update,
    "queries",
)

# LINK


# Link the query_panel parameters to the query_result update_query function
def sync_query_result(event):
    query_tabs.objects = [QueryResult(query).panel() for query in event.new]


# Watch for changes in the query_panel.queries list
settings.param.watch(sync_query_result, "queries")
query_tabs.objects = [
    QueryResult(query).panel() for query in query_builder.queries
]

# SET UP LAYOUT

header = pn.pane.Markdown(
    """
    # Metadata Query Builder
    Build simple metadata queries from dropdown options or .

    Note that the Subject ID and Modality options are dependent on the selected Project Name.
    """,
)
builder_switch = pn.widgets.Switch(name="Use chat builder", value=False)

header_row = pn.Row(
    header,
    pn.HSpacer(),
    pn.widgets.StaticText(value="<b>Use chat builder:</b>"),
    builder_switch,
)

query_builder_pane = query_builder.panel()
chat_builder_pane = chat_builder.panel()


def toggle_visibility(show_chat: bool):
    """Toggle visibility of the query builder and chat builder"""

    settings.use_chat = show_chat
    query_builder_pane.visible = not settings.use_chat
    chat_builder_pane.visible = settings.use_chat


builder_switch.param.watch(lambda event: toggle_visibility(event.new), "value")
builder_switch.value = settings.use_chat
toggle_visibility(settings.use_chat)


builder_col = pn.Column(
    header_row,
    query_builder_pane,
    chat_builder_pane,
    styles=outer_style,
    width=FIXED_WIDTH,
)

tab_col = pn.Column(
    query_tabs,
    styles=outer_style,
    width=FIXED_WIDTH,
)

main_col = pn.Column(
    builder_col,
    tab_col,
)

main_row = pn.Row(
    pn.HSpacer(),
    main_col,
    pn.HSpacer(),
).servable(title="Query Builder")
