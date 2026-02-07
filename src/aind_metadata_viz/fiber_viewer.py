"""App for viewing fiber implant locations in mouse brains"""

import asyncio
import base64
import io
import json
import math
from pathlib import Path

import altair as alt
import pandas as pd
import panel as pn
import param
import vl_convert as vlc

from aind_metadata_viz.utils import AIND_COLORS

pn.extension("vega")

# Metadata service and cache configuration
METADATA_SERVICE_URL = "http://aind-metadata-service"
CACHE_DIR = Path(".cache/procedures")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Visualization configuration (skull and fiber dimensions)
SKULL_LENGTH_MM = 25
SKULL_WIDTH_MM = 15

# Fiber colors and marker sizes
FIBER_COLORS = [
    "#FF6B6B",  # Red (Fiber_0)
    "#4CAF50",  # Green (Fiber_1)
    "#2196F3",  # Blue (Fiber_2)
    "#FF9800",  # Orange (Fiber_3)
    "#9C27B0",  # Purple (Fiber_4)
    "#00BCD4",  # Cyan (Fiber_5)
    "#FFC107",  # Amber (Fiber_6)
    "#795548",  # Brown (Fiber_7)
]
FIBER_MARKER_RADIUS = 0.4

# Bregma reference point styling
BREGMA_COLOR = "#000000"
BREGMA_EDGE_COLOR = "#000000"
BREGMA_RADIUS = 0.3

# Lambda reference point styling
LAMBDA_COLOR = "#000000"
LAMBDA_EDGE_COLOR = "#000000"
LAMBDA_RADIUS = 0.25

# Skull outline styling
SKULL_EDGE_COLOR = "#333333"
SKULL_ALPHA = 0.3

# Grid styling
GRID_COLOR = "gray"
GRID_ALPHA = 0.2

# Font sizes (increased by 25% from original)
TITLE_FONTSIZE = 21
FIBER_LABEL_FONTSIZE = 15
LEGEND_FONTSIZE = 13.5
REFERENCE_FONTSIZE = 12

# Figure output quality
DPI = 300

# Apply white background
css = """
body {
    background-color: #ffffff !important;
}
"""
pn.config.raw_css.append(css)


def get_cached_procedures(subject_id: str):
    """Get procedures from cache if available"""
    cache_path = CACHE_DIR / f"{subject_id}.json"
    if cache_path.exists():
        try:
            with open(cache_path, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error reading cache: {e}")
            return None
    return None


def save_to_cache(subject_id: str, procedures: dict):
    """Save procedures to cache"""
    cache_path = CACHE_DIR / f"{subject_id}.json"
    try:
        with open(cache_path, "w") as f:
            json.dump({"procedures": procedures}, f, indent=2)
    except Exception as e:
        print(f"Error writing cache: {e}")


def process_procedures_data(subject_id: str, procedures_data: dict) -> dict:
    """
    Process fiber procedures data for a subject.

    This function extracts fiber implant information from procedures data
    that was fetched by the client-side JavaScript.

    Args:
        subject_id: Subject identifier
        procedures_data: Procedures JSON data from metadata service

    Returns:
        dict with keys: procedures, fibers, subject_id, fiber_count
    """
    # Extract fiber implants from procedures
    fibers = []
    if procedures_data:
        subject_procedures = procedures_data.get("subject_procedures", [])

        for surgery in subject_procedures:
            procedures = surgery.get("procedures", [])

            for proc in procedures:
                proc_type = proc.get("object_type")

                # V2 schema: Probe implant with Fiber probe device
                if proc_type == "Probe implant":
                    implanted_device = proc.get("implanted_device", {})
                    device_type = implanted_device.get("object_type", "")

                    if device_type == "Fiber probe":
                        # Coordinates are in device_config.transform
                        device_config = proc.get("device_config", {})

                        # Default values
                        ml = 0
                        dv = None  # None means no depth available
                        ap = 0
                        angle = 0

                        # Extract coordinates from transform array
                        transform = device_config.get("transform", [])

                        for transform_obj in transform:
                            obj_type = transform_obj.get("object_type", "")

                            # Translation format:
                            # - 3 values: [AP, ML, burr_hole_depth] (current incomplete format, no fiber depth)
                            # - 4+ values: [AP, ML, burr_hole_depth, fiber_depth] (future complete format)
                            #   where burr_hole_depth is usually 0 and should be ignored
                            if obj_type == "Translation":
                                translation = transform_obj.get(
                                    "translation", []
                                )
                                if isinstance(translation, list):
                                    if len(translation) >= 4:
                                        # Future format: use 4th value as fiber depth
                                        ap = safe_float(translation[0])
                                        ml = safe_float(translation[1])
                                        # translation[2] is burr hole depth (ignored)
                                        dv = safe_float(translation[3])
                                    elif len(translation) >= 2:
                                        # Current format: only AP and ML are valid
                                        ap = safe_float(translation[0])
                                        ml = safe_float(translation[1])
                                        # Leave dv as None (no valid depth info)

                            # Rotation contains angles
                            elif obj_type == "Rotation":
                                angles = transform_obj.get("angles", [])
                                if isinstance(angles, list) and angles:
                                    # Use first non-zero angle if available
                                    for a in angles:
                                        if a is not None and a != 0:
                                            angle = safe_float(a)
                                            break

                        # Get targeted structure
                        primary_target = (
                            device_config.get("primary_targeted_structure")
                            or {}
                        )
                        target_name = primary_target.get(
                            "name", "Not specified in surgical request form"
                        )

                        fiber_info = {
                            "name": device_config.get(
                                "device_name", "Unknown"
                            ),
                            "ap": ap,
                            "ml": ml,
                            "dv": dv,
                            "angle": angle,
                            "unit": "millimeter",
                            "reference": (
                                device_config.get("coordinate_system") or {}
                            ).get("origin", "Bregma"),
                            "targeted_structure": target_name,
                        }
                        fibers.append(fiber_info)

    return {
        "procedures": procedures_data,
        "fibers": fibers,
        "subject_id": subject_id,
        "fiber_count": len(fibers),
    }


def get_procedures_data_from_cache_or_client(subject_id: str, client_data: dict = None) -> dict:
    """
    Get fiber procedures data from cache or client-provided data.

    This is a wrapper that checks cache first, or uses client-provided data.

    Args:
        subject_id: Subject identifier
        client_data: Optional procedures data fetched by client-side JavaScript

    Returns:
        dict with keys: procedures, fibers, subject_id, fiber_count, from_cache
    """
    # Check cache first
    cached_data = get_cached_procedures(subject_id)
    if cached_data:
        print(f"Loading procedures for {subject_id} from cache...")
        procedures_data = cached_data.get("procedures")
        from_cache = True
    elif client_data:
        print(f"Using client-provided data for {subject_id}")
        # Handle both direct response and wrapped in "data" key
        if isinstance(client_data, dict) and "data" in client_data:
            procedures_data = client_data["data"]
        else:
            procedures_data = client_data

        # Save to cache
        save_to_cache(subject_id, procedures_data)
        from_cache = False
    else:
        raise ValueError("No cached data and no client data provided")

    # Process the data
    result = process_procedures_data(subject_id, procedures_data)
    result["from_cache"] = from_cache
    return result


def safe_float(value, default=0.0):
    """Safely convert value to float, handling None and invalid values."""
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def create_ellipse_points(center_x, center_y, width, height, num_points=100):
    """Generate points for an ellipse outline."""
    points = []
    for i in range(num_points + 1):
        angle = 2 * math.pi * i / num_points
        x = center_x + (width / 2) * math.cos(angle)
        y = center_y + (height / 2) * math.sin(angle)
        points.append({"x": x, "y": y, "order": i})
    return points


def create_schematic(fibers, subject_id):
    """
    Create the complete fiber implant schematic using Altair.
    Returns Altair chart.
    """

    # Sort fibers by name
    def get_fiber_index(fiber):
        name = fiber.get("name", "Unknown")
        try:
            if "_" in name:
                return int(name.split("_")[-1])
            return 999
        except (ValueError, IndexError):
            return 999

    sorted_fibers = sorted(fibers, key=get_fiber_index)

    # Create skull outline points
    skull_points = create_ellipse_points(0, 0, SKULL_WIDTH_MM, SKULL_LENGTH_MM)
    skull_df = pd.DataFrame(skull_points)

    # Define consistent scale domains for all layers
    # 2:1 width:height ratio - x domain should be 2x the y domain
    x_scale = alt.Scale(domain=[-8, 48])  # 56 units
    y_scale = alt.Scale(domain=[-14, 14])  # 28 units

    # Create skull outline layer
    skull_layer = (
        alt.Chart(skull_df)
        .mark_line(color=SKULL_EDGE_COLOR, strokeWidth=2, opacity=0.5)
        .encode(
            x=alt.X("x:Q", scale=x_scale),
            y=alt.Y("y:Q", scale=y_scale),
            order="order:Q",
        )
    )

    # Grid lines data
    grid_data = []
    for ml in range(-6, 7, 2):
        grid_data.append(
            {"x": ml, "y": -13, "x2": ml, "y2": 13, "type": "vertical"}
        )
    for ap in range(-10, 11, 2):
        grid_data.append(
            {"x": -9, "y": ap, "x2": 9, "y2": ap, "type": "horizontal"}
        )
    grid_df = pd.DataFrame(grid_data)

    # Grid layer
    grid_layer = (
        alt.Chart(grid_df)
        .mark_rule(
            strokeDash=[3, 3],
            color=GRID_COLOR,
            opacity=GRID_ALPHA,
            strokeWidth=0.5,
        )
        .encode(
            x=alt.X("x:Q", scale=x_scale),
            y=alt.Y("y:Q", scale=y_scale),
            x2="x2:Q",
            y2="y2:Q",
        )
    )

    # Reference points (Bregma and Lambda)
    ref_points_df = pd.DataFrame(
        [
            {"x": 0, "y": 0, "label": "Bregma", "size": BREGMA_RADIUS * 200},
            {
                "x": 0,
                "y": -4.0,
                "label": "Lambda",
                "size": LAMBDA_RADIUS * 200,
            },
        ]
    )

    ref_layer = (
        alt.Chart(ref_points_df)
        .mark_circle(color=BREGMA_COLOR, stroke="black", strokeWidth=1.5)
        .encode(
            x=alt.X("x:Q", scale=x_scale),
            y=alt.Y("y:Q", scale=y_scale),
            size=alt.Size("size:Q", legend=None),
        )
    )

    ref_labels_df = pd.DataFrame(
        [
            {"x": 0, "y": -0.8, "label": "Bregma"},
            {"x": 0, "y": -4.6, "label": "Lambda"},
        ]
    )

    ref_text_layer = (
        alt.Chart(ref_labels_df)
        .mark_text(fontSize=REFERENCE_FONTSIZE, fontWeight="bold", dy=5)
        .encode(
            x=alt.X("x:Q", scale=x_scale),
            y=alt.Y("y:Q", scale=y_scale),
            text="label:N",
        )
    )

    # Fiber points
    fiber_data = []
    fiber_label_data = []
    for idx, fiber in enumerate(sorted_fibers):
        ml = safe_float(fiber.get("ml", 0))
        ap = safe_float(fiber.get("ap", 0))
        name = fiber.get("name", "Unknown")
        color = FIBER_COLORS[idx % len(FIBER_COLORS)]

        fiber_data.append(
            {
                "ml": ml,
                "ap": ap,
                "name": name,
                "color": color,
                "size": FIBER_MARKER_RADIUS * 400,
            }
        )

        # Smart label positioning: left side fibers get right-aligned labels,
        # right side fibers get left-aligned labels
        label_offset = 0.9
        if ml < 0:  # Left side - align right
            align = "right"
        else:  # Right side - align left
            align = "left"

        fiber_label_data.append(
            {
                "ml": ml,
                "ap": ap + label_offset,
                "name": name,
                "color": color,
                "align": align,
            }
        )

    fiber_df = pd.DataFrame(fiber_data)
    fiber_labels_df = pd.DataFrame(fiber_label_data)

    # Fiber points layer
    fiber_layer = (
        alt.Chart(fiber_df)
        .mark_circle(stroke="black", strokeWidth=2)
        .encode(
            x=alt.X("ml:Q", scale=x_scale),
            y=alt.Y("ap:Q", scale=y_scale),
            color=alt.Color("color:N", scale=None),
            size=alt.Size("size:Q", legend=None),
        )
    )

    # Split labels into left and right for different alignments
    left_labels_df = fiber_labels_df[fiber_labels_df["align"] == "right"]
    right_labels_df = fiber_labels_df[fiber_labels_df["align"] == "left"]

    # Left-side fiber labels (right-aligned)
    left_text_layer = (
        alt.Chart(left_labels_df)
        .mark_text(
            fontSize=FIBER_LABEL_FONTSIZE,
            fontWeight="bold",
            dy=-8,
            align="right",
        )
        .encode(
            x=alt.X("ml:Q", scale=x_scale),
            y=alt.Y("ap:Q", scale=y_scale),
            text="name:N",
            color=alt.Color("color:N", scale=None),
        )
    )

    # Right-side fiber labels (left-aligned)
    right_text_layer = (
        alt.Chart(right_labels_df)
        .mark_text(
            fontSize=FIBER_LABEL_FONTSIZE,
            fontWeight="bold",
            dy=-8,
            align="left",
        )
        .encode(
            x=alt.X("ml:Q", scale=x_scale),
            y=alt.Y("ap:Q", scale=y_scale),
            text="name:N",
            color=alt.Color("color:N", scale=None),
        )
    )

    # Orientation arrow (simplified - just text labels)
    arrow_x = -SKULL_WIDTH_MM / 2 - 1.5
    orientation_df = pd.DataFrame(
        [
            {
                "x": arrow_x,
                "y": 10,
                "label": "anterior",
                "size": REFERENCE_FONTSIZE,
            },
            {
                "x": arrow_x,
                "y": -10,
                "label": "posterior",
                "size": REFERENCE_FONTSIZE,
            },
            {
                "x": arrow_x,
                "y": 7,
                "label": "↑",
                "size": REFERENCE_FONTSIZE * 2,
            },
            {
                "x": arrow_x,
                "y": -7,
                "label": "↓",
                "size": REFERENCE_FONTSIZE * 2,
            },
        ]
    )

    orientation_layer = (
        alt.Chart(orientation_df)
        .mark_text(fontWeight="bold")
        .encode(
            x=alt.X("x:Q", scale=x_scale),
            y=alt.Y("y:Q", scale=y_scale),
            text="label:N",
            size=alt.Size("size:Q", legend=None),
        )
    )

    # Scale bar
    scale_bar_x = -SKULL_WIDTH_MM / 2 - 1.5
    scale_bar_y = -SKULL_LENGTH_MM / 2 - 1
    scale_bar_df = pd.DataFrame(
        [
            {
                "x": scale_bar_x,
                "y": scale_bar_y,
                "x2": scale_bar_x + 5,
                "y2": scale_bar_y,
            }
        ]
    )

    scale_bar_layer = (
        alt.Chart(scale_bar_df)
        .mark_rule(color="black", strokeWidth=3)
        .encode(
            x=alt.X("x:Q", scale=x_scale),
            y=alt.Y("y:Q", scale=y_scale),
            x2="x2:Q",
            y2="y2:Q",
        )
    )

    scale_text_df = pd.DataFrame(
        [{"x": scale_bar_x + 2.5, "y": scale_bar_y + 0.5, "label": "5 mm"}]
    )

    scale_text_layer = (
        alt.Chart(scale_text_df)
        .mark_text(fontSize=REFERENCE_FONTSIZE, fontWeight="bold")
        .encode(
            x=alt.X("x:Q", scale=x_scale),
            y=alt.Y("y:Q", scale=y_scale),
            text="label:N",
        )
    )

    # Legend text (positioned on right side)
    legend_data = []
    legend_x = 9.5  # Position on right side
    legend_y_start = 11
    within_fiber_spacing = 0.6  # Small spacing between coord and target lines
    between_fiber_spacing = 1.5  # Larger spacing between different fibers

    legend_data.append(
        {
            "x": legend_x,
            "y": legend_y_start,
            "text": "Fiber Details:",
            "color": "black",
        }
    )

    current_y = legend_y_start - 1.2
    for idx, fiber in enumerate(sorted_fibers):
        color = FIBER_COLORS[idx % len(FIBER_COLORS)]
        ap = safe_float(fiber.get("ap", 0))
        ml = safe_float(fiber.get("ml", 0))
        dv = fiber.get("dv")
        name = fiber.get("name", "Unknown")

        if dv is not None:
            text = f"{name}: AP={ap:.2f}, ML={ml:.2f}, DV={dv:.2f} mm"
        else:
            text = f"{name}: AP={ap:.2f}, ML={ml:.2f} mm"

        angle = safe_float(fiber.get("angle", 0))
        if abs(angle) > 1:
            text += f" ∠{angle}°"

        # Add coordinate line
        legend_data.append(
            {"x": legend_x, "y": current_y, "text": text, "color": color}
        )
        current_y -= within_fiber_spacing  # Small spacing to target line

        # Add target line
        target = fiber.get("targeted_structure", "Unknown")
        if not target or target == "" or target.lower() == "root":
            target = "Not specified in surgical request form"
        legend_data.append(
            {
                "x": legend_x,
                "y": current_y,
                "text": f"Target: {target}",
                "color": color,
            }
        )
        current_y -= between_fiber_spacing  # Larger spacing to next fiber

    legend_df = pd.DataFrame(legend_data)

    legend_layer = (
        alt.Chart(legend_df)
        .mark_text(fontSize=LEGEND_FONTSIZE, align="left", fontWeight="normal")
        .encode(
            x=alt.X("x:Q", scale=x_scale),
            y=alt.Y("y:Q", scale=y_scale),
            text="text:N",
            color=alt.Color("color:N", scale=None),
        )
    )

    # Title positioned at skull's left edge
    title_df = pd.DataFrame(
        [
            {
                "x": -SKULL_WIDTH_MM / 2,
                "y": 15,
                "text": f"Fiber Implant Locations - Top View | Subject: {subject_id}",
            }
        ]
    )

    title_layer = (
        alt.Chart(title_df)
        .mark_text(fontSize=TITLE_FONTSIZE, align="left", fontWeight="bold")
        .encode(
            x=alt.X("x:Q", scale=x_scale),
            y=alt.Y("y:Q", scale=y_scale),
            text="text:N",
        )
    )

    # Combine all layers
    chart = (
        alt.layer(
            grid_layer,
            skull_layer,
            ref_layer,
            ref_text_layer,
            fiber_layer,
            left_text_layer,
            right_text_layer,
            orientation_layer,
            scale_bar_layer,
            scale_text_layer,
            legend_layer,
            title_layer,
        )
        .properties(
            width=1400,
            height=700,
        )
        .configure_view(strokeWidth=0)
        .configure_axis(
            grid=False,
            domain=False,
            labels=False,
            ticks=False,
            title=None,
        )
        .resolve_scale(x="shared", y="shared")
    )

    return chart


def save_chart_to_base64(chart):
    """Save Altair chart to base64-encoded PNG string."""
    try:
        # Convert chart to Vega-Lite spec
        vega_spec = chart.to_dict()

        # Use vl-convert to convert to PNG
        png_data = vlc.vegalite_to_png(
            vl_spec=vega_spec,
            scale=2.0  # Higher resolution (2x DPI)
        )

        # Encode to base64
        img_base64 = base64.b64encode(png_data).decode("utf-8")
        return img_base64
    except Exception as e:
        print(f"Error saving chart to PNG: {e}")
        # Fallback: return None if PNG conversion fails
        return None


class MetadataFetcher(pn.reactive.ReactiveHTML):
    """
    Client-side data fetcher using JavaScript fetch API.

    This component runs in the browser and fetches data from the metadata service,
    which is accessible on the AIND internal network. The fetched data is then
    passed back to Python for processing.
    """

    subject_id = param.String(default="")
    data = param.Dict(default={})
    error = param.String(default="")

    _template = """
    <div id="fetcher" style="display: none;"></div>
    """

    _scripts = {
        'subject_id': """
            // This method is called automatically when subject_id changes
            if (data.subject_id && data.subject_id.trim() !== '') {
                const subjectId = data.subject_id.trim();

                data.error = "";
                data.data = {};

                const url = `http://aind-metadata-service/api/v2/procedures/${subjectId}`;

                fetch(url)
                    .then(response => {
                        if (response.status === 404) {
                            throw new Error(`No procedures found for subject ID: ${subjectId}`);
                        }
                        if (!response.ok) {
                            // Try to parse even if status is not OK (metadata service may return 400 with valid data)
                            return response.json().catch(() => {
                                throw new Error(`Metadata service returned status ${response.status}`);
                            });
                        }
                        return response.json();
                    })
                    .then(json => {
                        data.data = json;
                        data.error = "";
                    })
                    .catch(err => {
                        data.error = err.message || "Failed to fetch procedures data";
                        data.data = {};
                    });
            }
        """
    }


def build_panel_app():
    """
    Build the fiber viewer Panel app.

    The app displays fiber implant locations for mouse subjects using data
    from the metadata service. Results are cached locally for fast access.

    URL Parameters:
        subject_id (str): Subject identifier to load on page load

        Admin parameters (for cache management):
            clear_cache=all&confirm=yes: Clears all cached procedures.
                Example: /fiber_viewer?clear_cache=all&confirm=yes
                Use when metadata service is updated and all cached data
                needs to be refreshed (e.g., after depth values are fixed).

            clear_cache={subject_id}&confirm=yes: Clears cache for one subject.
                Example: /fiber_viewer?clear_cache=813992&confirm=yes
                Use to refresh data for a specific subject.
    """

    # Input widgets
    text_input = pn.widgets.TextInput(
        name="",
        placeholder="Enter subject_id (e.g., 813992)",
        sizing_mode="stretch_width",
        min_width=300,
    )

    generate_button = pn.widgets.Button(
        name="Generate Schematic",
        button_type="primary",
    )

    download_button = pn.widgets.Button(
        name="Download PNG",
        button_type="success",
        disabled=True,
    )

    copy_url_button = pn.widgets.Button(
        name="Copy Shareable URL",
        disabled=True,
    )

    # Output container and JS pane for downloads/clipboard
    output_col = pn.Column(sizing_mode="stretch_width")
    js_pane = pn.pane.HTML("", height=0, width=0)

    # Store current chart data for download
    current_chart_data = {"chart": None, "base64": None, "subject_id": None}

    # Create metadata fetcher (client-side)
    fetcher = MetadataFetcher()

    # Watch for data changes from the fetcher
    def process_fetched_data(event):
        """Process data that was fetched by the client-side JavaScript"""
        if not fetcher.data or not fetcher.data.get("subject_procedures"):
            return

        subject_id = text_input.value.strip()

        try:
            # Process the client-provided data
            data = get_procedures_data_from_cache_or_client(
                subject_id, fetcher.data
            )

            fibers = data.get("fibers", [])
            fiber_count = data.get("fiber_count", 0)

            if fiber_count == 0:
                output_col[:] = [
                    pn.pane.Markdown(
                        f"**No fiber implants found for subject {subject_id}**",
                        styles={
                            "background": "#fff8e1",
                            "border-left": f"4px solid {AIND_COLORS['yellow']}",
                            "padding": "10px",
                            "border-radius": "5px",
                        },
                    )
                ]
            else:
                # Generate schematic
                chart = create_schematic(fibers, subject_id)

                # Save chart data for download
                current_chart_data["chart"] = chart
                current_chart_data["base64"] = save_chart_to_base64(chart)
                current_chart_data["subject_id"] = subject_id

                # Display Altair chart (no sizing_mode to preserve aspect ratio)
                output_col[:] = [
                    pn.pane.Vega(chart),
                ]

                # Enable download and copy URL buttons
                download_button.disabled = False
                copy_url_button.disabled = False
        except Exception as e:
            output_col[:] = [
                pn.pane.Markdown(
                    f"**Error:** {str(e)}",
                    styles={
                        "background": "#fff5f5",
                        "border-left": f"4px solid {AIND_COLORS['red']}",
                        "padding": "10px",
                        "border-radius": "5px",
                    },
                )
            ]
        finally:
            output_col.loading = False

    def handle_fetch_error(event):
        """Handle errors from the client-side fetch"""
        if fetcher.error:
            output_col[:] = [
                pn.pane.Markdown(
                    f"**Error:** {fetcher.error}",
                    styles={
                        "background": "#fff5f5",
                        "border-left": f"4px solid {AIND_COLORS['red']}",
                        "padding": "10px",
                        "border-radius": "5px",
                    },
                )
            ]
            output_col.loading = False

    # Watch for data and error changes
    fetcher.param.watch(process_fetched_data, 'data')
    fetcher.param.watch(handle_fetch_error, 'error')

    # Button callback - trigger client-side fetch or use cache
    async def generate_callback(event):
        subject_id = text_input.value.strip()
        if not subject_id:
            output_col[:] = [
                pn.pane.Markdown("**Error:** Please enter a subject ID.")
            ]
            return

        # Check cache first
        cached_data = get_cached_procedures(subject_id)
        if cached_data:
            # Use cached data directly
            output_col.loading = True
            try:
                data = get_procedures_data_from_cache_or_client(subject_id)

                fibers = data.get("fibers", [])
                fiber_count = data.get("fiber_count", 0)

                if fiber_count == 0:
                    output_col[:] = [
                        pn.pane.Markdown(
                            f"**No fiber implants found for subject {subject_id}**",
                            styles={
                                "background": "#fff8e1",
                                "border-left": f"4px solid {AIND_COLORS['yellow']}",
                                "padding": "10px",
                                "border-radius": "5px",
                            },
                        )
                    ]
                else:
                    # Generate schematic
                    chart = create_schematic(fibers, subject_id)

                    # Save chart data for download
                    current_chart_data["chart"] = chart
                    current_chart_data["base64"] = save_chart_to_base64(chart)
                    current_chart_data["subject_id"] = subject_id

                    # Display Altair chart (no sizing_mode to preserve aspect ratio)
                    output_col[:] = [
                        pn.pane.Vega(chart),
                    ]

                    # Enable download and copy URL buttons
                    download_button.disabled = False
                    copy_url_button.disabled = False
            except Exception as e:
                output_col[:] = [
                    pn.pane.Markdown(
                        f"**Error:** {str(e)}",
                        styles={
                            "background": "#fff5f5",
                            "border-left": f"4px solid {AIND_COLORS['red']}",
                            "padding": "10px",
                            "border-radius": "5px",
                        },
                    )
                ]
            finally:
                output_col.loading = False
        else:
            # No cache - trigger client-side fetch
            output_col[:] = [
                pn.pane.Markdown(
                    f"Querying metadata service for subject_id {subject_id}. This should take about 30 seconds..."
                ),
                pn.Spacer(height=75),
            ]
            output_col.loading = True

            # Give Panel time to render the UI update
            await asyncio.sleep(0.2)

            # Trigger the fetch by setting subject_id
            fetcher.subject_id = subject_id

    def download_callback(event):
        """Download the current schematic as PNG."""
        if current_chart_data["base64"] is None:
            return

        subject_id = current_chart_data["subject_id"]
        img_base64 = current_chart_data["base64"]
        filename = f"fiber_schematic_{subject_id}.png"

        js_code = f"""
            var img_base64 = "{img_base64}";
            var binary = atob(img_base64);
            var array = new Uint8Array(binary.length);
            for (var i = 0; i < binary.length; i++) {{
                array[i] = binary.charCodeAt(i);
            }}
            var blob = new Blob([array], {{type: 'image/png'}});

            var url = window.URL.createObjectURL(blob);

            var a = document.createElement('a');
            a.href = url;
            a.download = "{filename}";

            document.body.appendChild(a);

            a.click();

            document.body.removeChild(a);

            window.URL.revokeObjectURL(url);
        """
        js_pane.object = ""
        js_pane.object = f"<script>{js_code}</script>"

    def copy_url_callback(event):
        """Copy current URL to clipboard."""
        js_code = """
            var url = window.location.href;
            navigator.clipboard.writeText(url).then(function() {
                console.log('URL copied to clipboard');
            }, function(err) {
                console.error('Failed to copy URL: ', err);
            });
        """
        js_pane.object = ""
        js_pane.object = f"<script>{js_code}</script>"

    generate_button.on_click(generate_callback)
    download_button.on_click(download_callback)
    copy_url_button.on_click(copy_url_callback)

    # Check for cache clearing request (admin feature)
    if pn.state.location:
        clear_cache = pn.state.location.query_params.get("clear_cache", "")
        confirm = pn.state.location.query_params.get("confirm", "")
    else:
        clear_cache = ""
        confirm = ""

    if clear_cache and confirm == "yes":
        try:
            if clear_cache == "all":
                # Clear all cached procedures
                cache_files = list(CACHE_DIR.glob("*.json"))
                count = len(cache_files)
                for cache_file in cache_files:
                    cache_file.unlink()
                output_col[:] = [
                    pn.pane.Markdown(
                        f"**Cache cleared:** Deleted {count} cached procedure file(s). "
                        f"All subsequent queries will fetch fresh data from metadata service.",
                        styles={
                            "background": "#e8f5e9",
                            "border-left": "4px solid #4caf50",
                            "padding": "10px",
                            "border-radius": "5px",
                        },
                    )
                ]
            else:
                # Clear cache for specific subject
                subject_id = clear_cache
                cache_file = CACHE_DIR / f"{subject_id}.json"
                if cache_file.exists():
                    cache_file.unlink()
                    output_col[:] = [
                        pn.pane.Markdown(
                            f"**Cache cleared:** Deleted cached data for subject {subject_id}. "
                            f"Next query will fetch fresh data from metadata service.",
                            styles={
                                "background": "#e8f5e9",
                                "border-left": "4px solid #4caf50",
                                "padding": "10px",
                                "border-radius": "5px",
                            },
                        )
                    ]
                else:
                    output_col[:] = [
                        pn.pane.Markdown(
                            f"**No cache found:** Subject {subject_id} has no cached data.",
                            styles={
                                "background": "#fff8e1",
                                "border-left": "4px solid #ff9800",
                                "padding": "10px",
                                "border-radius": "5px",
                            },
                        )
                    ]
        except Exception as e:
            output_col[:] = [
                pn.pane.Markdown(
                    f"**Error clearing cache:** {str(e)}",
                    styles={
                        "background": "#fff5f5",
                        "border-left": "4px solid #f44336",
                        "padding": "10px",
                        "border-radius": "5px",
                    },
                )
            ]

    # Get subject_id from URL and set text input manually
    if pn.state.location:
        url_subject_id = pn.state.location.query_params.get("subject_id", "")
        if url_subject_id:
            text_input.value = str(url_subject_id)

        # Sync for bidirectional URL updates
        pn.state.location.sync(text_input, {"value": "subject_id"})

    # Auto-run if subject_id is in URL
    if text_input.value:
        subject_id = text_input.value.strip()
        cached_data = get_cached_procedures(subject_id)

        if cached_data:
            # Use cached data for instant load
            try:
                results = get_procedures_data_from_cache_or_client(subject_id)
                fibers = results.get("fibers", [])
                fiber_count = results.get("fiber_count", 0)

                if fiber_count == 0:
                    output_col[:] = [
                        pn.pane.Markdown(
                            f"**No fiber implants found for subject {subject_id}**",
                            styles={
                                "background": "#fff8e1",
                                "border-left": f"4px solid {AIND_COLORS['yellow']}",
                                "padding": "10px",
                                "border-radius": "5px",
                            },
                        )
                    ]
                else:
                    chart = create_schematic(fibers, subject_id)
                    current_chart_data["chart"] = chart
                    current_chart_data["base64"] = save_chart_to_base64(chart)
                    current_chart_data["subject_id"] = subject_id
                    output_col[:] = [
                        pn.pane.Vega(chart),
                    ]
                    download_button.disabled = False
                    copy_url_button.disabled = False
            except Exception as e:
                output_col[:] = [
                    pn.pane.Markdown(
                        f"**Error:** {str(e)}",
                        styles={
                            "background": "#fff5f5",
                            "border-left": f"4px solid {AIND_COLORS['red']}",
                            "padding": "10px",
                            "border-radius": "5px",
                        },
                    )
                ]
        else:
            # No cache - show loading and trigger client-side fetch
            output_col[:] = [
                pn.pane.Markdown(
                    f"Loading data for subject_id {subject_id}..."
                ),
            ]
            output_col.loading = True
            # Trigger client-side fetch
            fetcher.subject_id = subject_id

    # Layout
    input_row = pn.Row(
        text_input,
        pn.Spacer(width=5),
        generate_button,
        pn.Spacer(width=5),
        download_button,
        pn.Spacer(width=5),
        copy_url_button,
        sizing_mode="stretch_width",
        align="center",
    )

    main_col = pn.Column(
        pn.pane.Markdown("## Fiber Schematic Viewer"),
        input_row,
        output_col,
        js_pane,
        fetcher,  # Hidden component for client-side fetching
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
