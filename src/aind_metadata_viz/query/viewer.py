"""Displaying queries"""
import param
import panel as pn
from aind_metadata_viz.query import FIXED_WIDTH


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
        self.query = query
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
