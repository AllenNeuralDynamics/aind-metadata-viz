"""This class builds a Panel view that displays why a particular record is not validating"""

import panel as pn
from aind_metadata_viz.database import docdb_api_client
# from aind_metadata_validator import 


class HallOfShame():

    def __init__(self):
        """Create a new instance of the HallOfShame view"""

        self.field_selector = pn.widgets.Select(name="Field", options=["_id", "name"])
        self.input = pn.widgets.TextInput(name="Value")
        self.exact_match = pn.widgets.Checkbox(name="Exact Match", value=False)

    def get_state(self):
        """Return the current state of the view"""

        if self.exact_match.value:
            query = {
                self.field_selector.value: self.input.value
            }
        else:
            query = {
                self.field_selector.value: {"$regex": self.input.value}
            }

        records = docdb_api_client.retrieve_docdb_records(
            query=query,
            limit=10
        )

        self.data = records
        validate()

    def validate(self):
        """Check if the first record in the data is valid"""
        print(self.data[0])
        

    def panel(self):
        """Build the panel view"""

        # Top row with search input and option to match exactly
        pn.row(self.field_selector, self.input, self.exact_match)

        # Second row with status information
        status = pn.widgets.StaticText(value=f"Found {len(self.data)} records, validating first record only.")

        # Below that display the results
        return pn.widgets.StaticText(value="Todo")
