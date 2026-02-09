"""
Fiber Implant Viewer - Interactive web application for visualizing fiber probe locations

OVERVIEW:
    This Panel web app displays fiber photometry probe implant locations on a top-down
    schematic of the mouse brain. Users enter a subject ID and see a
    visualization showing fiber coordinates and targeted brain structures (if available).

ARCHITECTURE:
    Client-Side Data Fetching (for deployment):
        - JavaScript fetch() runs in user's browser to access aind-metadata-service
        - Works when deployed to cloud and accessed from AIND internal network
        - Overcomes network boundary: cloud server can't reach on-prem metadata service
        - See MetadataFetcher class for implementation

    Caching:
        - The metadata service is slow (~30 seconds to fetch data) so we cache procedures data locally to speed up display when cached data is available.
        - Procedures data cached locally in .cache/procedures/ directory
        - Never expires automatically (use URL params below to clear)
        - Near instant load when cached data available
        - Clear cache via URL: ?clear_cache=all&confirm=yes (all subjects)
        - Clear cache via URL: ?clear_cache=SUBJECT_ID&confirm=yes (one subject)

DATA FLOW:
    1. User enters subject ID
    2. Check local cache first
       - If cached: skip to step 5
       - If not cached: continue to step 3
    3. Client-side JavaScript fetches from aind-metadata-service API
    4. Raw procedures JSON passed from browser to Python, saved to cache
    5. extract_fiber_metadata() extracts coordinates from transform data
    6. create_schematic() generates Altair visualization
    7. Display interactive chart with download/share options

KEY COMPONENTS:
    - MetadataFetcher: ReactiveHTML component with JavaScript fetch logic
    - extract_fiber_metadata(): Parse fiber coordinates from device config
    - create_schematic(): Generate Altair/Vega chart with all visual layers
    - render_fiber_visualization(): Core rendering logic with error handling
    - create_styled_pane(): Styled error/warning/success messages with expandable details

VISUALIZATION:
    - Skull outline (ellipse)
    - Reference points (Bregma, Lambda)
    - Fiber markers (colored circles with labels)
    - Legend with coordinates and targeted structures
    - Orientation indicators and scale bar
    - Download as high-res PNG

ERROR HANDLING:
    - Simple message shown by default
    - Expandable details with full traceback/HTTP response
    - Client-side errors capture: URL, status code, response body
    - Python errors capture: full traceback

URL PARAMETERS:
    - subject_id: Auto-load visualization for this subject
    - clear_cache=all&confirm=yes: Clear all cached data (admin)
    - clear_cache={id}&confirm=yes: Clear cache for specific subject
"""

import asyncio
import base64
import json
import math
import traceback
from pathlib import Path

import altair as alt
import pandas as pd
import panel as pn
import param
import vl_convert as vlc

from aind_metadata_viz.utils import AIND_COLORS

pn.extension("vega")

# Metadata service and cache configuration
METADATA_SERVICE_URL = "https://aind-metadata-service"
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
    try:
        return json.load(cache_path.open()) if cache_path.exists() else None
    except Exception as e:
        print(f"Error reading cache: {e}")
        return None


def save_to_cache(subject_id: str, procedures: dict):
    """Save procedures to cache"""
    try:
        json.dump(
            {"procedures": procedures},
            (CACHE_DIR / f"{subject_id}.json").open("w"),
            indent=2,
        )
    except Exception as e:
        print(f"Error writing cache: {e}")


def extract_fiber_metadata(device_config: dict) -> dict:
    """Extract fiber coordinates and metadata from device config"""
    ml = ap = angle = 0
    dv = None  # None means no depth available

    # Extract coordinates from transform array
    for transform_obj in device_config.get("transform", []):
        obj_type = transform_obj.get("object_type", "")

        if obj_type == "Translation":
            translation = transform_obj.get("translation", [])
            if isinstance(translation, list) and len(translation) >= 2:
                ap = safe_float(translation[0])
                ml = safe_float(translation[1])
                # Optional: 4th value is fiber depth (3rd is burr hole depth, ignored)
                if len(translation) >= 4:
                    dv = safe_float(translation[3])

        elif obj_type == "Rotation":
            angles = transform_obj.get("angles", [])
            # Use first non-zero angle
            angle = next((safe_float(a) for a in angles if a), 0)

    # Get targeted structure
    target = (device_config.get("primary_targeted_structure") or {}).get(
        "name", "Not specified in surgical request form"
    )

    return {
        "name": device_config.get("device_name", "Unknown"),
        "ap": ap,
        "ml": ml,
        "dv": dv,
        "angle": angle,
        "unit": "millimeter",
        "reference": (device_config.get("coordinate_system") or {}).get(
            "origin", "Bregma"
        ),
        "targeted_structure": target,
    }


def process_procedures_data(subject_id: str, procedures_data: dict) -> dict:
    """Extract fiber implant information from procedures data"""
    fibers = []

    for surgery in procedures_data.get("subject_procedures", []):
        for proc in surgery.get("procedures", []):
            # V2 schema: Probe implant with Fiber probe device
            if proc.get("object_type") == "Probe implant":
                device = proc.get("implanted_device", {})
                if device.get("object_type") == "Fiber probe":
                    device_config = proc.get("device_config", {})
                    fibers.append(extract_fiber_metadata(device_config))

    return {
        "procedures": procedures_data,
        "fibers": fibers,
        "subject_id": subject_id,
        "fiber_count": len(fibers),
    }


def get_procedures_data_from_cache_or_client(
    subject_id: str, client_data: dict = None
) -> dict:
    """Get fiber procedures data from cache or client-provided data"""
    # Try cache first
    cached_data = get_cached_procedures(subject_id)
    if cached_data:
        print(f"Loading procedures for {subject_id} from cache...")
        procedures_data = cached_data["procedures"]
        from_cache = True
    elif client_data:
        print(f"Using client-provided data for {subject_id}")
        # Handle response wrapped in "data" key
        procedures_data = client_data.get("data", client_data)
        save_to_cache(subject_id, procedures_data)
        from_cache = False
    else:
        raise ValueError("No cached data and no client data provided")

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

    High-level orchestration function that composes all visualization layers.
    Returns Altair chart.
    """

    # Sort fibers by name for consistent display
    def get_fiber_index(fiber):
        name = fiber.get("name", "Unknown")
        try:
            if "_" in name:
                return int(name.split("_")[-1])
            return 999
        except (ValueError, IndexError):
            return 999

    sorted_fibers = sorted(fibers, key=get_fiber_index)

    # Define consistent scale domains for all layers (2:1 width:height ratio)
    x_scale = alt.Scale(domain=[-8, 48])  # 56 units
    y_scale = alt.Scale(domain=[-14, 14])  # 28 units

    # Helper for common x/y encoding with consistent scales
    def xy_encode(x_col="x", y_col="y"):
        return {
            "x": alt.X(f"{x_col}:Q", scale=x_scale),
            "y": alt.Y(f"{y_col}:Q", scale=y_scale),
        }

    # Step 1: Create skull outline
    skull_layer = _create_skull_layer(xy_encode)

    # Step 2: Create reference points (Bregma, Lambda)
    ref_layer, ref_text_layer = _create_reference_layers(xy_encode)

    # Step 3: Create fiber markers and labels
    fiber_layer, left_text_layer, right_text_layer = _create_fiber_layers(
        sorted_fibers, xy_encode
    )

    # Step 4: Create orientation indicators
    orientation_layer = _create_orientation_layer(xy_encode)

    # Step 5: Create scale bar
    scale_bar_layer, scale_text_layer = _create_scale_layers(xy_encode)

    # Step 6: Create legend with fiber details
    legend_layer = _create_legend_layer(sorted_fibers, xy_encode)

    # Step 7: Create title
    title_layer = _create_title_layer(subject_id, xy_encode)

    # Step 8: Compose all layers into final chart
    chart = (
        alt.layer(
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
        .properties(width=1400, height=700)
        .configure_view(strokeWidth=0)
        .configure_axis(
            grid=False, domain=False, labels=False, ticks=False, title=None
        )
        .resolve_scale(x="shared", y="shared")
    )

    return chart


def _create_skull_layer(xy_encode):
    """Create skull outline ellipse layer"""
    skull_points = create_ellipse_points(0, 0, SKULL_WIDTH_MM, SKULL_LENGTH_MM)
    skull_df = pd.DataFrame(skull_points)
    return (
        alt.Chart(skull_df)
        .mark_line(color=SKULL_EDGE_COLOR, strokeWidth=2, opacity=0.5)
        .encode(**xy_encode(), order="order:Q")
    )


def _create_reference_layers(xy_encode):
    """Create Bregma and Lambda reference point layers (markers + labels)"""
    # Reference point markers
    ref_points_df = pd.DataFrame(
        [
            {"x": 0, "y": 0, "label": "Bregma", "size": BREGMA_RADIUS * 200},
            {"x": 0, "y": -4.0, "label": "Lambda", "size": LAMBDA_RADIUS * 200},
        ]
    )
    ref_layer = (
        alt.Chart(ref_points_df)
        .mark_circle(color=BREGMA_COLOR, stroke="black", strokeWidth=1.5)
        .encode(**xy_encode(), size=alt.Size("size:Q", legend=None))
    )

    # Reference point labels
    ref_labels_df = pd.DataFrame(
        [
            {"x": 0, "y": -0.8, "label": "Bregma"},
            {"x": 0, "y": -4.6, "label": "Lambda"},
        ]
    )
    ref_text_layer = (
        alt.Chart(ref_labels_df)
        .mark_text(fontSize=REFERENCE_FONTSIZE, fontWeight="bold", dy=5)
        .encode(**xy_encode(), text="label:N")
    )

    return ref_layer, ref_text_layer


def _create_fiber_layers(sorted_fibers, xy_encode):
    """Create fiber marker and label layers"""
    # Build fiber data for markers and labels
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

        # Smart label positioning: left side gets right-aligned, right side gets left-aligned
        label_offset = 0.9
        align = "right" if ml < 0 else "left"

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

    # Fiber markers layer
    fiber_layer = (
        alt.Chart(fiber_df)
        .mark_circle(stroke="black", strokeWidth=2)
        .encode(
            **xy_encode("ml", "ap"),
            color=alt.Color("color:N", scale=None),
            size=alt.Size("size:Q", legend=None),
        )
    )

    # Helper to create label layer with alignment
    def create_label_layer(labels_df, alignment):
        return (
            alt.Chart(labels_df)
            .mark_text(
                fontSize=FIBER_LABEL_FONTSIZE,
                fontWeight="bold",
                dy=-8,
                align=alignment,
            )
            .encode(
                **xy_encode("ml", "ap"),
                text="name:N",
                color=alt.Color("color:N", scale=None),
            )
        )

    # Create separate layers for left and right aligned labels
    left_text_layer = create_label_layer(
        fiber_labels_df[fiber_labels_df["align"] == "right"], "right"
    )
    right_text_layer = create_label_layer(
        fiber_labels_df[fiber_labels_df["align"] == "left"], "left"
    )

    return fiber_layer, left_text_layer, right_text_layer


def _create_orientation_layer(xy_encode):
    """Create anterior/posterior orientation indicators"""
    arrow_x = -SKULL_WIDTH_MM / 2 - 1.5
    orientation_df = pd.DataFrame(
        [
            {"x": arrow_x, "y": 10, "label": "anterior", "size": REFERENCE_FONTSIZE},
            {"x": arrow_x, "y": -10, "label": "posterior", "size": REFERENCE_FONTSIZE},
            {"x": arrow_x, "y": 7, "label": "↑", "size": REFERENCE_FONTSIZE * 2},
            {"x": arrow_x, "y": -7, "label": "↓", "size": REFERENCE_FONTSIZE * 2},
        ]
    )
    return (
        alt.Chart(orientation_df)
        .mark_text(fontWeight="bold")
        .encode(**xy_encode(), text="label:N", size=alt.Size("size:Q", legend=None))
    )


def _create_scale_layers(xy_encode):
    """Create scale bar and label layers"""
    scale_bar_x = -SKULL_WIDTH_MM / 2 - 1.5
    scale_bar_y = -SKULL_LENGTH_MM / 2 - 1

    # Scale bar line
    scale_bar_df = pd.DataFrame(
        [{"x": scale_bar_x, "y": scale_bar_y, "x2": scale_bar_x + 5, "y2": scale_bar_y}]
    )
    scale_bar_layer = (
        alt.Chart(scale_bar_df)
        .mark_rule(color="black", strokeWidth=3)
        .encode(**xy_encode(), x2="x2:Q", y2="y2:Q")
    )

    # Scale bar label
    scale_text_df = pd.DataFrame(
        [{"x": scale_bar_x + 2.5, "y": scale_bar_y + 0.5, "label": "5 mm"}]
    )
    scale_text_layer = (
        alt.Chart(scale_text_df)
        .mark_text(fontSize=REFERENCE_FONTSIZE, fontWeight="bold")
        .encode(**xy_encode(), text="label:N")
    )

    return scale_bar_layer, scale_text_layer


def _create_legend_layer(sorted_fibers, xy_encode):
    """Create legend with fiber coordinates and targeted structures"""
    legend_data = []
    legend_x = 9.5  # Position on right side
    legend_y_start = 11
    within_fiber_spacing = 0.6  # Spacing between coord and target lines
    between_fiber_spacing = 1.5  # Spacing between different fibers

    legend_data.append(
        {"x": legend_x, "y": legend_y_start, "text": "Fiber Details:", "color": "black"}
    )

    current_y = legend_y_start - 1.2
    for idx, fiber in enumerate(sorted_fibers):
        color = FIBER_COLORS[idx % len(FIBER_COLORS)]
        ap = safe_float(fiber.get("ap", 0))
        ml = safe_float(fiber.get("ml", 0))
        dv = fiber.get("dv")
        name = fiber.get("name", "Unknown")

        # Coordinate line
        if dv is not None:
            text = f"{name}: AP={ap:.2f}, ML={ml:.2f}, DV={dv:.2f} mm"
        else:
            text = f"{name}: AP={ap:.2f}, ML={ml:.2f} mm"

        angle = safe_float(fiber.get("angle", 0))
        if abs(angle) > 1:
            text += f" ∠{angle}°"

        legend_data.append({"x": legend_x, "y": current_y, "text": text, "color": color})
        current_y -= within_fiber_spacing

        # Target line
        target = fiber.get("targeted_structure", "Unknown")
        if not target or target == "" or target.lower() == "root":
            target = "Not specified in surgical request form"
        legend_data.append(
            {"x": legend_x, "y": current_y, "text": f"Target: {target}", "color": color}
        )
        current_y -= between_fiber_spacing

    legend_df = pd.DataFrame(legend_data)
    return (
        alt.Chart(legend_df)
        .mark_text(fontSize=LEGEND_FONTSIZE, align="left", fontWeight="normal")
        .encode(**xy_encode(), text="text:N", color=alt.Color("color:N", scale=None))
    )


def _create_title_layer(subject_id, xy_encode):
    """Create title layer"""
    title_df = pd.DataFrame(
        [
            {
                "x": -SKULL_WIDTH_MM / 2,
                "y": 15,
                "text": f"Fiber Implant Locations - Top View | Subject: {subject_id}",
            }
        ]
    )
    return (
        alt.Chart(title_df)
        .mark_text(fontSize=TITLE_FONTSIZE, align="left", fontWeight="bold")
        .encode(**xy_encode(), text="text:N")
    )



def save_chart_to_base64(chart):
    """Save Altair chart to base64-encoded PNG string."""
    try:
        # Convert chart to Vega-Lite spec
        vega_spec = chart.to_dict()

        # Use vl-convert to convert to PNG
        png_data = vlc.vegalite_to_png(
            vl_spec=vega_spec, scale=2.0  # Higher resolution (2x DPI)
        )

        # Encode to base64
        img_base64 = base64.b64encode(png_data).decode("utf-8")
        return img_base64
    except Exception as e:
        print(f"Error saving chart to PNG: {e}")
        # Fallback: return None if PNG conversion fails
        return None


# Styling helpers
def create_styled_pane(message: str, style_type: str, details: str = None):
    """
    Create a styled pane for displaying messages.

    Args:
        message: The message text (supports markdown)
        style_type: One of 'error', 'warning', 'success'
        details: Optional detailed information (shown in expandable section)

    Returns:
        Panel Markdown pane with appropriate styling
    """
    styles = {
        "error": {
            "background": "#fff5f5",
            "border-left": f"4px solid {AIND_COLORS['red']}",
            "padding": "10px",
            "border-radius": "5px",
        },
        "warning": {
            "background": "#fff8e1",
            "border-left": f"4px solid {AIND_COLORS['yellow']}",
            "padding": "10px",
            "border-radius": "5px",
        },
        "success": {
            "background": "#e8f5e9",
            "border-left": "4px solid #4caf50",
            "padding": "10px",
            "border-radius": "5px",
        },
    }

    if details:
        # Add expandable details section
        content = f"""{message}

<details>
<summary><b>Click to expand error details</b></summary>

```
{details}
```
</details>"""
    else:
        content = message

    return pn.pane.Markdown(content, styles=styles[style_type])


def render_fiber_visualization(subject_id: str, data: dict):
    """
    Core rendering logic for fiber visualization.

    Takes processed fiber data and generates the appropriate display panes.

    Args:
        subject_id: Subject identifier
        data: Processed data dict with keys: fibers, fiber_count

    Returns:
        tuple: (
            panes_list: List of panes to display,
            chart_data: Dict with chart, base64, subject_id keys,
            enable_buttons: Boolean indicating if download buttons should be enabled
        )
    """
    fibers = data.get("fibers", [])
    fiber_count = data.get("fiber_count", 0)

    if fiber_count == 0:
        pane = create_styled_pane(
            f"**No fiber implants found for subject {subject_id}**", "warning"
        )
        return (
            [pane],
            {"chart": None, "base64": None, "subject_id": None},
            False,
        )

    # Generate schematic
    chart = create_schematic(fibers, subject_id)
    chart_data = {
        "chart": chart,
        "base64": save_chart_to_base64(chart),
        "subject_id": subject_id,
    }

    return [pn.pane.Vega(chart)], chart_data, True


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
    error_details = param.String(default="")

    _template = """
    <div id="fetcher" style="display: none;"></div>
    """

    _scripts = {
        "subject_id": f"""
if (data.subject_id && data.subject_id.trim()) {{
    const subjectId = data.subject_id.trim();
    const url = `{METADATA_SERVICE_URL}/api/v2/procedures/${{subjectId}}`;

    data.error = "";
    data.error_details = "";
    data.data = {{}};

    fetch(url)
        .then(response => {{
            const status = response.status;
            const statusText = response.statusText;

            // Try to get response body for error details
            return response.text().then(body => {{
                if (status === 404) {{
                    const details = `URL: ${{url}}\\nStatus: ${{status}} ${{statusText}}\\nResponse: ${{body}}`;
                    data.error_details = details;
                    throw new Error(`No procedures found for subject ID: ${{subjectId}}`);
                }}
                if (!response.ok) {{
                    const details = `URL: ${{url}}\\nStatus: ${{status}} ${{statusText}}\\nResponse: ${{body}}`;
                    data.error_details = details;
                    throw new Error(`Metadata service returned status ${{status}}`);
                }}
                // Parse successful response
                try {{
                    return JSON.parse(body);
                }} catch (e) {{
                    const details = `URL: ${{url}}\\nStatus: ${{status}} ${{statusText}}\\nResponse: ${{body}}\\nParse error: ${{e.message}}`;
                    data.error_details = details;
                    throw new Error('Invalid JSON response from metadata service');
                }}
            }});
        }})
        .then(json => {{
            data.data = json;
            data.error = "";
            data.error_details = "";
        }})
        .catch(err => {{
            data.error = err.message || "Failed to fetch procedures data";
            if (!data.error_details) {{
                data.error_details = `URL: ${{url}}\\nError: ${{err.stack || err.message}}`;
            }}
            data.data = {{}};
        }});
}}
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

    # Helper to render and update all UI elements
    def render_and_update_ui(subject_id, data):
        """Render visualization and update all UI state"""
        panes, chart_data, enable_buttons = render_fiber_visualization(
            subject_id, data
        )
        output_col[:] = panes
        current_chart_data.update(chart_data)
        download_button.disabled = not enable_buttons
        copy_url_button.disabled = not enable_buttons

    # Watch for data changes from the fetcher
    def process_fetched_data(_event):
        """Process data that was fetched by the client-side JavaScript"""
        if not fetcher.data or not fetcher.data.get("subject_procedures"):
            return

        subject_id = text_input.value.strip()
        try:
            data = get_procedures_data_from_cache_or_client(
                subject_id, fetcher.data
            )
            render_and_update_ui(subject_id, data)
        except Exception as e:
            tb = traceback.format_exc()
            output_col[:] = [
                create_styled_pane(
                    f"**Error processing data:** {str(e)}", "error", details=tb
                )
            ]
        finally:
            output_col.loading = False

    def handle_fetch_error(_event):
        """Handle errors from the client-side fetch"""
        if fetcher.error:
            output_col[:] = [
                create_styled_pane(
                    f"**Error:** {fetcher.error}",
                    "error",
                    details=(
                        fetcher.error_details
                        if fetcher.error_details
                        else None
                    ),
                )
            ]
            output_col.loading = False

    # Watch for data and error changes
    fetcher.param.watch(process_fetched_data, "data")
    fetcher.param.watch(handle_fetch_error, "error")

    # Button callback - trigger client-side fetch or use cache
    async def generate_callback(_event):
        subject_id = text_input.value.strip()
        if not subject_id:
            output_col[:] = [
                create_styled_pane(
                    "**Error:** Please enter a subject ID.", "error"
                )
            ]
            return

        # Check cache first
        cached_data = get_cached_procedures(subject_id)
        if cached_data:
            # Use cached data directly
            output_col.loading = True
            try:
                data = get_procedures_data_from_cache_or_client(subject_id)
                render_and_update_ui(subject_id, data)
            except Exception as e:
                tb = traceback.format_exc()
                output_col[:] = [
                    create_styled_pane(
                        f"**Error:** {str(e)}", "error", details=tb
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

    def download_callback(_event):
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

    def copy_url_callback(_event):
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
                    create_styled_pane(
                        f"**Cache cleared:** Deleted {count} cached procedure file(s). "
                        f"All subsequent queries will fetch fresh data from metadata service.",
                        "success",
                    )
                ]
            else:
                # Clear cache for specific subject
                subject_id = clear_cache
                cache_file = CACHE_DIR / f"{subject_id}.json"
                if cache_file.exists():
                    cache_file.unlink()
                    output_col[:] = [
                        create_styled_pane(
                            f"**Cache cleared:** Deleted cached data for subject {subject_id}. "
                            f"Next query will fetch fresh data from metadata service.",
                            "success",
                        )
                    ]
                else:
                    output_col[:] = [
                        create_styled_pane(
                            f"**No cache found:** Subject {subject_id} has no cached data.",
                            "warning",
                        )
                    ]
        except Exception as e:
            tb = traceback.format_exc()
            output_col[:] = [
                create_styled_pane(
                    f"**Error clearing cache:** {str(e)}", "error", details=tb
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
                data = get_procedures_data_from_cache_or_client(subject_id)
                render_and_update_ui(subject_id, data)
            except Exception as e:
                tb = traceback.format_exc()
                output_col[:] = [
                    create_styled_pane(
                        f"**Error:** {str(e)}", "error", details=tb
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
