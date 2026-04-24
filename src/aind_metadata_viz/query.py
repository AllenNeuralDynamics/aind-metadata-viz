"""App for generating metadata queries"""

import panel as pn

from aind_metadata_viz.utils import BASE_CSS
from biodata_query.panel.builder import QueryBuilder
from biodata_query.panel.results import QueryResults


pn.extension(
    'tabulator',
    sizing_mode="stretch_width",
    raw_css=[
        BASE_CSS,
        """
        .tabulator { font-size: 12px !important; }
        .tabulator .tabulator-col-title,
        .tabulator .tabulator-cell { font-size: 12px !important; padding: 2px 6px !important; }
        .tabulator .tabulator-row { min-height: 22px !important; }
        """
    ],
)

builder = QueryBuilder()
results = QueryResults()
builder.param.watch(lambda e: results.param.update(query=e.new), "query")

pn.Column(
    pn.pane.Markdown("# Metadata Query Builder"),
    builder,
    results,
    sizing_mode="stretch_width",
).servable(title="Query Builder")
