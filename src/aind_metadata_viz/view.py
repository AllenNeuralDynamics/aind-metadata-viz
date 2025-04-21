"""App for viewing individual metadata assets"""
import os

import panel as pn
import param


from aind_data_access_api.document_db import MetadataDbClient

from aind_metadata_viz.utils import outer_style, AIND_COLORS
from aind_metadata_viz.database import ALL_FILES

from aind_metadata_validator.core_validator import validate_core_metadata
from aind_metadata_validator.utils import MetadataState

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


# State sync
class Settings(param.Parameterized):
    """Top-level settings for QC app"""

    name = param.String(default="")


settings = Settings()
pn.state.location.sync(settings, {"name": "name"})


def get_record(name):
    """Get a record from the database by name"""
    records = docdb_api_client.retrieve_docdb_records(
        filter_query={"name": name},
        limit=1,
    )

    if len(records) == 0:
        return None
    return records[0]


class MetadataView(param.Parameterized):
    """Class for viewing metadata records"""

    record = param.Dict(default=None)
    files_present = param.List(default=[])
    describedBys = param.Dict(default={})
    buttons = param.Dict(default={})
    file_panels = param.Dict(default={})

    def __init__(self, **params):
        super().__init__(**params)

    def set_record(self, record):
        """Set the record to be viewed"""
        self.record = record
        self.files_present = []

        if not self.record:
            return

        for file in ALL_FILES:

            self.file_panels[file] = pn.Column(
                styles=outer_style,
                width=FIXED_WIDTH,
            )

            if file in self.record and self.record[file]:
                # Track that this file is present
                self.files_present.append(file)

                # Remove the unneecssary describedBy field
                if "describedBy" in self.record[file]:
                    self.describedBys[file] = self.record[file]["describedBy"]
                    del self.record[file]["describedBy"]

                # Validate the file and store errors, if any
                # [todo]

                self.file_panel(file)

            self.buttons[file] = pn.widgets.Button(name=f"{file}", button_type="primary" if file in self.files_present else "default", disabled=True)
            pn.bind(self._toggle_visibility, self.buttons[file], file=file, watch=True)

    def _toggle_visibility(self, event, file):
        """Toggle the visibility of a file"""
        self.file_panels[file].visible = not self.file_panels[file].visible

    def header_panel(self):
        """Return a header panel with simple metadata information"""

        md = f"## {self.record['name']}"

        return pn.pane.Markdown(md)

    def button_panel(self):
        """Return a header panel with buttons for viewing each file

        Missing files have their button disabled
        """
        objects = []

        for file in ALL_FILES:
            if file in self.buttons.keys():
                self.buttons[file].disabled = file not in self.files_present
                objects.append(
                    self.buttons[file]
                )

        return pn.Row(*objects)

    def header(self):
        """Compile the full header"""

        return pn.Column(
            self.header_panel(),
            self.button_panel(),
            styles=outer_style,
            width=FIXED_WIDTH,
        )

    def file_panel(self, file: str):
        """Create a panel for viewing a single file's contents"""

        if file not in self.record:
            return f"File {file} not found in record"

        md_header = pn.pane.Markdown(
            f"## {file} \n"
            f"aind-data-schema link: [{file}.py]({self.describedBys[file]})"
        )
        data = pn.pane.JSON(self.record[file], width=FIXED_WIDTH-50)

        self.file_panels[file].objects = [
            md_header,
            data,
        ]

    def panel(self):
        """Create a panel for viewing the metadata record"""
        if self.record is None:
            return pn.pane.Markdown("<span style='color:white;'>No record selected. Set a record by adding ?name={your-asset-name} to the URL</span>")

        main_col = pn.Column(
            self.header(),
        )

        for file in self.files_present:
            main_col.append(self.file_panels[file])

        return main_col


metadata_view = MetadataView()
metadata_view.set_record(get_record(settings.name))
metadata_view_pane = metadata_view.panel()

main_row = pn.Row(
    pn.HSpacer(),
    metadata_view_pane,
    pn.HSpacer(),
)
main_row.servable(title="Metadata View")
