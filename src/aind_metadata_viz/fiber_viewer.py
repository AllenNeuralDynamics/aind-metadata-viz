"""App for viewing fiber implant locations in mouse brains"""

import panel as pn
from aind_metadata_viz.utils import AIND_COLORS, outer_style, FIXED_WIDTH

pn.extension()

# Apply AIND background styling
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


def build_panel_app():
    """Build the fiber viewer Panel app"""

    # Input widgets
    input_label = pn.pane.Markdown("**Enter Subject ID:**")
    text_input = pn.widgets.TextInput(
        placeholder="e.g., 123456",
        sizing_mode="stretch_width",
    )

    generate_button = pn.widgets.Button(
        name="Generate Schematic",
        button_type="primary",
        disabled=True,
    )

    # Output container
    output_col = pn.Column(sizing_mode="stretch_width")

    # Enable/disable generate button based on text input
    def update_generate_button(event):
        generate_button.disabled = not bool(text_input.value.strip())

    text_input.param.watch(update_generate_button, "value")

    # Button callback (placeholder for now)
    def generate_callback(event):
        output_col[:] = [
            pn.pane.Markdown("**Generate button clicked!**")
        ]

    generate_button.on_click(generate_callback)

    # Layout
    input_row = pn.Row(
        text_input,
        pn.Spacer(width=5),
        generate_button,
        sizing_mode="stretch_width",
        align="center",
    )

    main_col = pn.Column(
        "# Fiber Schematic Viewer",
        input_label,
        input_row,
        output_col,
        sizing_mode="stretch_width",
    )

    # Center with spacers
    main_row = pn.Row(
        pn.HSpacer(),
        main_col,
        pn.HSpacer(),
    )

    return main_row


app = build_panel_app()
app.servable(title="Fiber Viewer")
