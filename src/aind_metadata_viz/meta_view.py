"""App for viewing individual metadata assets"""
import os

import panel as pn
import param

from aind_data_access_api.document_db import MetadataDbClient

from aind_metadata_viz.utils import outer_style

API_GATEWAY_HOST = os.getenv("API_GATEWAY_HOST", "api.allenneuraldynamics-test.org")
DATABASE = os.getenv("DATABASE", "metadata_index")
COLLECTION = os.getenv("COLLECTION", "data_assets")

docdb_api_client = MetadataDbClient(
    host=API_GATEWAY_HOST,
    database=DATABASE,
    collection=COLLECTION,
)

records = docdb_api_client.retrieve_docdb_records(
    filter_query={},
    limit=1,
)
record = records[0]


class MetadataView(param.Parameterized):
    """Class for viewing metadata records"""

    record = param.Dict(default=None)

    def __init__(self, record=None, **params):
        super().__init__(**params)
        self.record = record if record is not None else self.record

    @param.depends("record", watch=True)
    def panel(self):
        """Create a panel for viewing the metadata record"""
        if self.record is None:
            return pn.pane.Markdown("No record selected")

        # Create a panel for the metadata record
        record_pane = pn.pane.Markdown(
            f"## Metadata Record\n\n{self.record}",
            styles=outer_style,
        )

        return record_pane

metadata_view = MetadataView(record=record)
metadata_view_pane = metadata_view.panel()

metadata_view_pane.servable(title="Metadata View")
