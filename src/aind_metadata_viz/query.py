"""App for generating metadata queries"""
import os
from typing import Optional

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


class QueryPanel(param.Parameterized):
    """Class for generating simple metadata queries"""

    project_name = param.String(default="", allow_None=True)
    subject_ids = param.List(default=[], allow_None=True)
    modalities = param.List(default=[], allow_None=True)
    query = param.Dict(default={})

    def __init__(self, **params):
        super().__init__(**params)
        self.query_pane = pn.pane.JSON(
            object={},
            name="Query",
            width=FIXED_WIDTH-50,
        )
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

        self.project_name_selector.link(self, value="project_name")
        self.subject_id_selector.link(self, value="subject_ids")
        self.modality_selector.link(self, value="modalities")

    def options_panel(self):
        """Create the options panel for the query"""

        return pn.Column(
            pn.Row(
                self.project_name_selector,
                self.subject_id_selector,
                self.modality_selector,
            ),
            width=FIXED_WIDTH-50,
        )

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

    @pn.depends("project_name", "subject_ids", "modalities", watch=True)
    def update_query_panel(self):
        """Update the query panel content dynamically"""
        query_dict = {}

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

        self.query = query_dict
        self.query_pane.object = query_dict

    def query_panel(self):
        """Return the query panel containing the JSONEditor"""
        return self.query_pane

    def panel(self):
        """Return the full panel"""
        return pn.Column(
            self.options_panel(),
            pn.pane.Markdown("## Query"),
            self.query_panel(),
            width=FIXED_WIDTH,
        )


class QueryResult(param.Parameterized):
    """Class for displaying query results"""

    query = param.Dict(default={})

    def __init__(self, **params):
        super().__init__(**params)

        self.query_pane = pn.pane.DataFrame(
            escape=False,
            index=False,
        )

    def update_query(self, query: dict):
        """Update the query and fetch results"""

        if query:
            self.query_pane.object = None
            self.query_result = docdb_api_client.retrieve_docdb_records(
                filter_query=query,
                projection={
                    "name": 1,
                }
            )

            df = pd.DataFrame(self.query_result)

            # Rename name to Name
            if "name" in df.columns:
                df.rename(columns={"name": "Name"}, inplace=True)

            # Add a column that generates a link to the view app
            df["View Record"] = [
                f'<a href="http://localhost:5006/view?name={record["name"]}" target="_blank">View</a>'
                for record in self.query_result
            ]
            # Remove _id column
            if "_id" in df.columns:
                df.drop(columns=["_id"], inplace=True)

            self.query_pane.object = df

    def panel(self):
        """Return the query result panel"""
        return pn.Column(
            self.query_pane,
            width=FIXED_WIDTH-50,
            styles=outer_style,
        )


query_panel = QueryPanel()
query_result = QueryResult()

saved_subject_ids = pn.state.location.query_params.get("subject_ids", [])
saved_modalities = pn.state.location.query_params.get("modalities", [])
pn.state.location.sync(query_panel, {
        "project_name": "project_name",
        "subject_ids": "subject_ids",
        "modalities": "modalities",
    }
)


# Link the query_panel parameters to the query_result update_query function
def sync_query_result(events):
    query_result.update_query(query_panel.query)


# Watch for changes in the query_panel parameters
query_panel.param.watch(sync_query_result, ['project_name', 'subject_ids', 'modalities'])

# RUN INITIAL UPDATES

query_panel.project_name_selector.value = query_panel.project_name
query_panel.update_query_panel()
query_panel.update_subject_id_options()
query_panel.update_modality_options()
query_result.update_query(query_panel.query)
query_panel.subject_id_selector.value = saved_subject_ids
query_panel.modality_selector.value = saved_modalities


# SET UP LAYOUT

header = pn.pane.Markdown(
    """
    # Metadata Query Builder
    Build simple metadata queries from dropdown options and then view associated metadata.

    Note that the Subject ID and Modality options are dependent on the selected Project Name.
    """,
)

main_col = pn.Column(
    header,
    query_panel.options_panel(),
    query_panel.query_panel(),
    query_result.panel(),
    styles=outer_style,
    width=FIXED_WIDTH,
)

main_row = pn.Row(
    pn.HSpacer(),
    main_col,
    pn.HSpacer(),
).servable(title="Query Builder")
