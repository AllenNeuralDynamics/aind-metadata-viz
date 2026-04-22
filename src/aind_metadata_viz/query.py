"""App for generating metadata queries"""

import panel as pn

from aind_metadata_viz.utils import outer_style, AIND_COLORS
from biodata_query.panel.builder import QueryBuilder
from biodata_query.panel.results import QueryResults


pn.extension(
    'tabulator',
    sizing_mode="stretch_width",
    raw_css=["""
        body, .bk-root { font-size: 12px !important; }
        .tabulator { font-size: 12px !important; }
        .tabulator .tabulator-col-title,
        .tabulator .tabulator-cell { font-size: 12px !important; padding: 2px 6px !important; }
        .tabulator .tabulator-row { min-height: 22px !important; }
    """],
)

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

builder = QueryBuilder()
results = QueryResults()
builder.param.watch(lambda e: results.param.update(query=e.new), "query")

pn.Column(
    pn.pane.Markdown("# Metadata Query Builder"),
    builder,
    results,
    sizing_mode="stretch_width",
).servable(title="Query Builder")
