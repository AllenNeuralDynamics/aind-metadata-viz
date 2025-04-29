"""App for generating metadata queries"""
import os
from typing import Optional
import json

import pandas as pd
import panel as pn
import param

from aind_metadata_viz.utils import outer_style, AIND_COLORS, sort_with_none

from aind_data_access_api.document_db import MetadataDbClient

FIXED_WIDTH = 1200
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


API_GATEWAY_HOST = os.getenv("API_GATEWAY_HOST", "api.allenneuraldynamics-test.org")
DATABASE = os.getenv("DATABASE", "metadata_index")
COLLECTION = os.getenv("COLLECTION", "data_assets")

docdb_api_client = MetadataDbClient(
    host=API_GATEWAY_HOST,
    database=DATABASE,
    collection=COLLECTION,
)

DF_KEYS = ["name"]


# Helpers to get option lists
@pn.cache(ttl=86400)  # Cache for 24 hours
def get_project_names():
    project_options = docdb_api_client.aggregate_docdb_records(
        pipeline=[
            {
                "$group": {
                    "_id": "$data_description.project_name"
                }
            },
            {
                "$sort": {
                    "_id": 1  # Optional: sorts alphabetically
                }
            }
        ]
    )
    project_options = [project["_id"] for project in project_options]

    if project_options:
        project_options = sort_with_none(project_options)
    return project_options


@pn.cache(ttl=86400)  # Cache for 24 hours
def get_subject_ids(project_name: Optional[str]):
    """Get subject IDs"""

    if not project_name:
        return []

    subject_options = docdb_api_client.aggregate_docdb_records(
        pipeline=[
            {  # filter by project name
                "$match": {
                    "data_description.project_name": project_name
                }
            },
            {
                "$group": {
                    "_id": "$subject.subject_id"
                }
            },
        ]
    )
    subject_options = [subject["_id"] for subject in subject_options]
    if subject_options:
        subject_options = sort_with_none(subject_options)
    return subject_options


@pn.cache(ttl=86400)  # Cache for 24 hours
def get_modalities(project_name: Optional[str]):
    """Get modality abbreviations"""

    if not project_name:
        return []

    modality_options = docdb_api_client.aggregate_docdb_records(
        pipeline=[
            {  # filter by project name
                "$match": {
                    "data_description.project_name": project_name
                }
            },
            {
                "$unwind": "$data_description.modality"
            },
            {
                "$group": {
                    "_id": "$data_description.modality.abbreviation"
                }
            },
        ]
    )
    modality_options = [modality["_id"] for modality in modality_options]
    if modality_options:
        modality_options = sort_with_none(modality_options)
    return modality_options


@pn.cache(ttl=86400)  # Cache for 24 hours
def get_session_types(project_name: Optional[str]):
    """Get session types"""

    if not project_name:
        return []

    session_type_options = docdb_api_client.aggregate_docdb_records(
        pipeline=[
            {  # filter by project name
                "$match": {
                    "data_description.project_name": project_name
                }
            },
            {
                "$group": {
                    "_id": "$session.session_type"
                }
            },
        ]
    )
    session_type_options = [session["_id"] for session in session_type_options]
    if session_type_options:
        session_type_options = sort_with_none(session_type_options)
    return session_type_options


@pn.cache(ttl=60*60)  # Cache for 1 hour
def get_docdb_records(filter_query: dict):
    """Get a set of records"""
    return docdb_api_client.retrieve_docdb_records(
        filter_query=filter_query,
        projection={key: 1 for key in DF_KEYS},
    )


class QueryViewer(param.Parameterized):
    """Class for displaying the result of a query"""

    query = param.Dict(default={}, allow_None=True)

    def __init__(self, query, **params):
        super().__init__(**params)
        self.query = query
        self.query_pane = pn.pane.JSON(
            object=self.query,
            width=FIXED_WIDTH-50,
        )

        self.hidden_html = pn.pane.HTML(
            object="",
            width=0,
            height=0,
        )

        self.copy_button = pn.widgets.Button(
            name="",
            icon="copy",
            button_type="primary",
            width=40,
            height=30,
        )
        self.copy_button.on_click(self.copy_to_clipboard)

    def update(self, query: dict):
        """Update the query pane with a new query"""
        self.query_pane.object = query

    def copy_to_clipboard(self, event):
        """Copy the query to clipboard"""
        query_data = self.query.copy()
        if "_name" in query_data:
            del query_data["_name"]

        clipboard_js = f"""
        <script>
        navigator.clipboard.writeText('{json.dumps(query_data)}');
        </script>
        """
        self.hidden_html.object = clipboard_js
        self.hidden_html.object = ""

    def panel(self):
        """Return the query viewer panel"""
        return pn.Row(
            self.hidden_html,
            pn.Column(self.query_pane, width=FIXED_WIDTH-150),
            pn.Column(self.copy_button, align='end'),
            width=FIXED_WIDTH-50
        )


class QueryBuilder(param.Parameterized):
    """Class for generating simple metadata queries"""

    project_name = param.String(default="", allow_None=True)
    subject_ids = param.List(default=[], allow_None=True)
    modalities = param.List(default=[], allow_None=True)
    session_types = param.List(default=[], allow_None=True)
    queries = param.List(default=[])

    def __init__(self, **params):
        super().__init__(**params)
        self.query_viewer = QueryViewer({})
        self.project_name_selector = pn.widgets.Select(
            name="Project Name",
            options=[""] + get_project_names(),  # Add empty string option
            value=self.project_name,
        )
        self.subject_id_selector = pn.widgets.MultiChoice(
            name="Subject IDs",
            options=[""] + get_subject_ids(None),  # Add empty string option
            value=self.subject_ids,
            disabled=True,
        )
        self.modality_selector = pn.widgets.MultiChoice(
            name="Modalities",
            options=[""] + get_modalities(None),  # Add empty string option
            value=self.modalities,
            disabled=True,
        )
        self.session_type_selector = pn.widgets.MultiChoice(
            name="Session Types",
            options=[""] + get_session_types(None),  # Add empty string option
            value=[],
            width=500,
            disabled=True,
        )

        self.project_name_selector.link(self, value="project_name")
        self.subject_id_selector.link(self, value="subject_ids")
        self.modality_selector.link(self, value="modalities")
        self.session_type_selector.link(self, value="session_types")

        self.query_button = pn.widgets.Button(
            name="Submit query",
            button_type="primary",
        )
        pn.bind(self.save_query, self.query_button, watch=True)

    def options_panel(self):
        """Create the options panel for the query"""

        selector_col = pn.Column(
            pn.Row(
                self.project_name_selector,
                self.subject_id_selector,
                self.modality_selector,
            ),
            pn.Row(
                self.session_type_selector,
            ),
            width=FIXED_WIDTH-150,
        )

        submit_col = pn.Column(
            self.query_button,
            width=100,
        )

        return pn.Row(selector_col, submit_col)

    @pn.depends("project_name", watch=True)
    def update_subject_id_options(self):
        """Clear the subject ID value and change options"""

        if self.project_name != "":
            # update subject ID options
            self.subject_id_selector.options = get_subject_ids(self.project_name)
            self.subject_id_selector.disabled = False
        else:
            # reset subject ID options
            self.subject_id_selector.options = []
            self.subject_id_selector.disabled = True

        self.subject_id_selector.value = []
        self.subject_ids = []

    @pn.depends("project_name", watch=True)
    def update_modality_options(self):
        """Clear the modality value and change options"""

        if self.project_name != "":
            # update modality options
            self.modality_selector.options = get_modalities(self.project_name)
            self.modality_selector.disabled = False
        else:
            # reset modality options
            self.modality_selector.options = []
            self.modality_selector.disabled = True

        self.modality_selector.value = []
        self.modalities = []

    @pn.depends("project_name", watch=True)
    def update_session_type_options(self):
        """Clear the session type value and change options"""

        if self.project_name != "":
            # update session type options
            self.session_type_selector.options = get_session_types(self.project_name)
            self.session_type_selector.disabled = False
        else:
            # reset session type options
            self.session_type_selector.options = []
            self.session_type_selector.disabled = True

        self.session_type_selector.value = []
        self.session_types = []

    @pn.depends("project_name", "subject_ids", "modalities", "session_types", watch=True)
    def update_query_panel(self):
        """Update the query panel content dynamically"""
        self.query_button.disabled = False
        query_dict = {"_name": f"Query {len(self.queries) + 1}"}

        if self.project_name != "":
            query_dict["data_description.project_name"] = self.project_name

        if self.subject_ids != []:
            query_dict["subject.subject_id"] = {
                "$in": self.subject_ids
            }

        if self.modalities != []:
            query_dict["data_description.modality.abbreviation"] = {
                "$in": self.modalities
            }

        if self.session_types != []:
            query_dict["session.session_type"] = {
                "$in": self.session_types
            }

        self.query_viewer.update(query_dict)

        if len(query_dict.keys()) <= 1:
            self.query_button.disabled = True
            self.query_button.name = "Cannot submit empty query"
            self.query_button.button_type = "danger"
        else:
            self.query_button.name = "Submit query"
            self.query_button.disabled = False
            self.query_button.button_type = "primary"

    def save_query(self, event):
        """Store the current query in the queries list"""
        self.queries = self.queries + [self.query_viewer.query_pane.object]
        self.query_button.disabled = True

    def panel(self):
        """Return the full panel"""
        return pn.Column(
            self.options_panel(),
            pn.pane.Markdown("## Query"),
            self.query_viewer.panel(),
            width=FIXED_WIDTH,
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
            width=FIXED_WIDTH-50,
            name=self.query_name,
        )


query_builder = QueryBuilder()

saved_subject_ids = pn.state.location.query_params.get("subject_ids", [])
saved_modalities = pn.state.location.query_params.get("modalities", [])
saved_session_types = pn.state.location.query_params.get("session_types", [])
pn.state.location.sync(query_builder, {
        "project_name": "project_name",
        "subject_ids": "subject_ids",
        "modalities": "modalities",
        "session_types": "session_types",
        "queries": "queries",
    }
)

query_tabs = pn.Tabs(width=FIXED_WIDTH-50)


# Link the query_panel parameters to the query_result update_query function
def sync_query_result(event):
    query_tabs.objects = [QueryResult(query).panel() for query in event.new]


# Watch for changes in the query_panel.queries list
query_builder.param.watch(sync_query_result, 'queries')

# RUN INITIAL UPDATES

query_builder.project_name_selector.value = query_builder.project_name
query_builder.update_query_panel()
query_builder.update_subject_id_options()
query_builder.update_modality_options()
query_builder.update_session_type_options()
query_builder.subject_id_selector.value = saved_subject_ids
query_builder.modality_selector.value = saved_modalities
query_builder.session_type_selector.value = saved_session_types
query_tabs.objects = [QueryResult(query).panel() for query in query_builder.queries]

# SET UP LAYOUT

header = pn.pane.Markdown(
    """
    # Metadata Query Builder
    Build simple metadata queries from dropdown options and then view associated metadata.

    Note that the Subject ID and Modality options are dependent on the selected Project Name.
    """,
)

builder_col = pn.Column(
    header,
    query_builder.panel(),
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
