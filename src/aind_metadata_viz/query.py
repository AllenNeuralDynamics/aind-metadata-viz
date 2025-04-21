"""App for generating metadata queries"""
import os

import panel as pn
import param

from aind_metadata_viz.utils import outer_style, AIND_COLORS

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
    return project_options


class QueryPanel(param.Parameterized):
    """Class for generating simple metadata queries"""

    project_name = param.String(default="", allow_None=True)

    def __init__(self, **params):
        super().__init__(**params)
        self.query_pane = pn.widgets.JSONEditor(
            value={},
            name="Query",
            width=FIXED_WIDTH-50,
        )

    def options_panel(self):
        """Create the options panel for the query"""
        project_name_selector = pn.widgets.Select(
            name="Project Name",
            options=[""] + get_project_names(),  # Add empty string option
            value=self.project_name,
        )
        project_name_selector.link(self, value="project_name")

        return pn.Column(
            project_name_selector,
            width=FIXED_WIDTH-50,
        )

    @pn.depends("project_name", watch=True)
    def update_query_panel(self):
        """Update the query panel content dynamically"""
        query_dict = {}

        if self.project_name != "":
            query_dict["project_name"] = self.project_name

        self.query_pane.value = query_dict

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


query_panel = QueryPanel()

header = pn.pane.Markdown(
    """
    # Metadata Query Builder
    Build simple metadata queries from dropdown options and then view associated metadata.
    """,
)

main_col = pn.Column(
    header,
    query_panel.options_panel(),
    query_panel.query_panel(),
    styles=outer_style,
    width=FIXED_WIDTH,
)

main_row = pn.Row(
    pn.HSpacer(),
    main_col,
    pn.HSpacer(),
).servable(title="Query Builder")
