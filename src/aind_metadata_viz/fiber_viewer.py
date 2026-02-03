"""App for viewing fiber implant locations in mouse brains"""

import json
from pathlib import Path
import requests
import panel as pn
from aind_metadata_viz.utils import AIND_COLORS
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.patches import Circle

pn.extension()

# Metadata service URL (internal service, same as validation.py)
METADATA_SERVICE_URL = "http://aind-metadata-service"

# Cache directory (same as Flask app)
CACHE_DIR = Path(".cache/procedures")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

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


def get_procedures_data(subject_id: str) -> dict:
    """
    Get fiber procedures data for a subject.

    Cache: Never expires (delete files manually to invalidate)

    Args:
        subject_id: Subject identifier

    Returns:
        dict with keys: procedures, fibers, subject_id, fiber_count, from_cache
    """
    # Check cache first
    cached_data = get_cached_procedures(subject_id)
    if cached_data:
        print(f"Loading procedures for {subject_id} from cache...")
        procedures_data = cached_data.get("procedures")
        from_cache = True
    else:
        # Query metadata service (same pattern as validation.py)
        print(f"Retrieving procedures for {subject_id} from metadata service...")
        try:
            response = requests.get(
                f"{METADATA_SERVICE_URL}/api/v2/procedures/{subject_id}"
            )

            if response.status_code == 404:
                raise ValueError(f"No procedures found for subject ID: {subject_id}")

            # Try to parse JSON response (metadata service may return 400 with valid data)
            try:
                procedures_data = response.json()
                # Handle both direct response and wrapped in "data" key
                if isinstance(procedures_data, dict) and "data" in procedures_data:
                    procedures_data = procedures_data["data"]
            except ValueError:
                raise ValueError(
                    f"Metadata service returned invalid JSON (status {response.status_code})"
                )

        except requests.RequestException as e:
            raise ValueError(f"Failed to retrieve procedures metadata: {str(e)}")

        # Save to cache
        save_to_cache(subject_id, procedures_data)
        from_cache = False

    # Extract fiber implants from procedures (matching Flask app logic)
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
                        dv = 0
                        ap = 0
                        angle = 0

                        # Extract coordinates from transform array
                        transform = device_config.get("transform", [])

                        for transform_obj in transform:
                            obj_type = transform_obj.get("object_type", "")

                            # Translation contains [AP, ML, DV]
                            if obj_type == "Translation":
                                translation = transform_obj.get("translation", [])
                                if isinstance(translation, list) and len(translation) >= 3:
                                    ap = safe_float(translation[0])
                                    ml = safe_float(translation[1])
                                    dv = safe_float(translation[2])

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
                        primary_target = device_config.get("primary_targeted_structure") or {}
                        target_name = primary_target.get("name", "Not specified in surgical request form")

                        fiber_info = {
                            "name": device_config.get("device_name", "Unknown"),
                            "ap": ap,
                            "ml": ml,
                            "dv": dv,
                            "angle": angle,
                            "unit": "millimeter",
                            "reference": (device_config.get("coordinate_system") or {}).get("origin", "Bregma"),
                            "targeted_structure": target_name,
                        }
                        fibers.append(fiber_info)

    return {
        "procedures": procedures_data,
        "fibers": fibers,
        "subject_id": subject_id,
        "fiber_count": len(fibers),
        "from_cache": from_cache,
    }


# Visualization configuration (from Flask app config.py)
SKULL_LENGTH_MM = 25
SKULL_WIDTH_MM = 15

FIBER_COLORS = [
    '#FF6B6B',  # Red (Fiber_0)
    '#4CAF50',  # Green (Fiber_1)
    '#2196F3',  # Blue (Fiber_2)
    '#FF9800',  # Orange (Fiber_3)
    '#9C27B0',  # Purple (Fiber_4)
    '#00BCD4',  # Cyan (Fiber_5)
    '#FFC107',  # Amber (Fiber_6)
    '#795548',  # Brown (Fiber_7)
]

FIBER_MARKER_RADIUS = 0.4
BREGMA_COLOR = '#000000'
BREGMA_EDGE_COLOR = '#000000'
BREGMA_RADIUS = 0.3

LAMBDA_COLOR = '#000000'
LAMBDA_EDGE_COLOR = '#000000'
LAMBDA_RADIUS = 0.25

SKULL_FILL_COLOR = '#F5F5F5'
SKULL_EDGE_COLOR = '#333333'
SKULL_ALPHA = 0.3

GRID_COLOR = 'gray'
GRID_ALPHA = 0.2
GRID_LINESTYLE = ':'

TITLE_FONTSIZE = 16.8
LABEL_FONTSIZE = 14.4
FIBER_LABEL_FONTSIZE = 12
LEGEND_FONTSIZE = 10.8
REFERENCE_FONTSIZE = 9.6

FIGURE_WIDTH = 7.2
FIGURE_HEIGHT = 9
DPI = 300


def safe_float(value, default=0.0):
    """Safely convert value to float, handling None and invalid values."""
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def create_skull_outline(ax):
    """Draw a stylized mouse skull outline (top-down view)."""
    skull = patches.Ellipse(
        (0, 0),
        width=SKULL_WIDTH_MM,
        height=SKULL_LENGTH_MM,
        facecolor=SKULL_FILL_COLOR,
        edgecolor=SKULL_EDGE_COLOR,
        linewidth=2,
        alpha=SKULL_ALPHA,
        zorder=1,
    )
    ax.add_patch(skull)

    # Bregma marker (origin)
    bregma = Circle(
        (0, 0),
        radius=BREGMA_RADIUS,
        facecolor=BREGMA_COLOR,
        edgecolor=BREGMA_EDGE_COLOR,
        linewidth=1.5,
        zorder=5,
    )
    ax.add_patch(bregma)
    ax.text(
        0,
        -0.8,
        "Bregma",
        ha="center",
        va="top",
        fontsize=REFERENCE_FONTSIZE,
        fontweight="bold",
        color=BREGMA_EDGE_COLOR,
    )

    # Lambda marker (posterior reference point, typically ~4mm behind Bregma)
    lambda_ap = -4.0
    lambda_marker = Circle(
        (0, lambda_ap),
        radius=LAMBDA_RADIUS,
        facecolor=LAMBDA_COLOR,
        edgecolor=LAMBDA_EDGE_COLOR,
        linewidth=1.5,
        zorder=5,
        alpha=0.7,
    )
    ax.add_patch(lambda_marker)
    ax.text(
        0,
        lambda_ap - 0.6,
        "Lambda",
        ha="center",
        va="top",
        fontsize=REFERENCE_FONTSIZE,
        color=LAMBDA_EDGE_COLOR,
        alpha=0.7,
    )

    # Add coordinate grid
    add_coordinate_grid(ax)


def add_coordinate_grid(ax):
    """Add a subtle coordinate grid for reference."""
    # Vertical gridlines (ML axis)
    for ml in range(-6, 7, 2):
        ax.axvline(
            ml, color=GRID_COLOR, linestyle=GRID_LINESTYLE, linewidth=0.5, alpha=GRID_ALPHA
        )

    # Horizontal gridlines (AP axis)
    for ap in range(-10, 11, 2):
        ax.axhline(
            ap, color=GRID_COLOR, linestyle=GRID_LINESTYLE, linewidth=0.5, alpha=GRID_ALPHA
        )


def draw_fiber(ax, fiber, fiber_index):
    """Draw a single fiber implant on the schematic."""
    ml = safe_float(fiber.get("ml", 0))
    ap = safe_float(fiber.get("ap", 0))
    name = fiber.get("name", "Unknown")

    # Choose color
    color = FIBER_COLORS[fiber_index % len(FIBER_COLORS)]

    # Draw fiber insertion point
    fiber_point = Circle(
        (ml, ap), radius=FIBER_MARKER_RADIUS, facecolor=color, edgecolor="black", linewidth=2, zorder=10
    )
    ax.add_patch(fiber_point)

    # Label the fiber - position based on left/right side to avoid overlap
    label_offset_y = 0.9
    if ml < 0:  # Left side - align to right corner
        ha = "right"
    else:  # Right side - align to left corner
        ha = "left"

    ax.text(
        ml,
        ap + label_offset_y,
        name,
        ha=ha,
        va="bottom",
        fontsize=FIBER_LABEL_FONTSIZE,
        fontweight="bold",
        color="black",
        bbox=dict(boxstyle="round,pad=0.3", facecolor=color, alpha=0.7, edgecolor="black"),
    )


def create_legend_text(fibers):
    """
    Create legend data with fiber details and colors.
    Returns list of (text, color) tuples.
    """
    legend_items = [("Fiber Details:", "black")]
    for idx, fiber in enumerate(fibers):
        color = FIBER_COLORS[idx % len(FIBER_COLORS)]

        ap = safe_float(fiber.get("ap", 0))
        ml = safe_float(fiber.get("ml", 0))
        dv = safe_float(fiber.get("dv", 0))
        angle = safe_float(fiber.get("angle", 0))
        name = fiber.get("name", "Unknown")

        text = f"{name}: AP={ap:.2f}, ML={ml:.2f}, DV={dv:.2f} mm"
        if abs(angle) > 1:
            text += f" ∠{angle}°"

        target = fiber.get("targeted_structure", "Unknown")
        if not target or target == "" or target.lower() == "root":
            target = "Not specified in surgical request form"
        text += f"\nTarget: {target}"

        legend_items.append((text, color))
    return legend_items


def create_schematic(fibers, subject_id):
    """
    Create the complete fiber implant schematic.
    Returns matplotlib figure.
    """
    # Sort fibers by name (Fiber_0, Fiber_1, Fiber_2...) to ensure consistent order
    def get_fiber_index(fiber):
        name = fiber.get("name", "Unknown")
        try:
            if "_" in name:
                return int(name.split("_")[-1])
            return 999
        except (ValueError, IndexError):
            return 999

    sorted_fibers = sorted(fibers, key=get_fiber_index)

    # Create figure
    fig, ax = plt.subplots(figsize=(FIGURE_WIDTH, FIGURE_HEIGHT))

    # Draw skull outline
    create_skull_outline(ax)

    # Draw each fiber
    for idx, fiber in enumerate(sorted_fibers):
        draw_fiber(ax, fiber, idx)

    # Set up axes
    ax.set_xlim(-SKULL_WIDTH_MM / 2 - 2, SKULL_WIDTH_MM / 2 + 2)
    ax.set_ylim(-SKULL_LENGTH_MM / 2 - 2, SKULL_LENGTH_MM / 2 + 2)
    ax.set_aspect("equal")

    # Labels
    ax.set_xlabel("Medial-Lateral (mm)", fontsize=LABEL_FONTSIZE, fontweight="bold")
    ax.set_ylabel("Anterior-Posterior (mm)", fontsize=LABEL_FONTSIZE, fontweight="bold")

    # Title
    title = f"Fiber Implant Locations - Top View\nSubject: {subject_id}"
    ax.set_title(title, fontsize=TITLE_FONTSIZE, fontweight="bold", pad=20)

    # Add legend with fiber details (color-coded text, no box)
    legend_items = create_legend_text(sorted_fibers)

    # Add colored text lines
    legend_y = 0.98
    line_spacing = 0.035

    for text, color in legend_items:
        ax.text(
            0.02,
            legend_y,
            text,
            transform=ax.transAxes,
            fontsize=LEGEND_FONTSIZE,
            verticalalignment="top",
            color=color,
            fontweight="bold" if color != "black" else "normal",
            family="monospace",
        )
        # Count newlines for proper spacing
        num_lines = text.count("\n") + 1
        legend_y -= line_spacing * num_lines

    # Grid
    ax.grid(True, alpha=GRID_ALPHA, linestyle="--")

    # Tight layout
    plt.tight_layout()

    return fig


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
    )

    # Output container
    output_col = pn.Column(sizing_mode="stretch_width")

    # Button callback
    def generate_callback(event):
        subject_id = text_input.value.strip()
        if not subject_id:
            output_col[:] = [
                pn.pane.Markdown("**Error:** Please enter a subject ID.")
            ]
            return

        # Show loading message
        output_col[:] = [
            pn.pane.Markdown(f"Querying metadata service for subject {subject_id}...")
        ]
        output_col.loading = True

        try:
            # Get procedures data (file-based cache, never expires)
            data = get_procedures_data(subject_id)

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
                fig = create_schematic(fibers, subject_id)

                # Display matplotlib figure
                output_col[:] = [
                    pn.pane.Matplotlib(fig, tight=True, sizing_mode="stretch_width"),
                ]

                # Close figure to free memory
                plt.close(fig)
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
        pn.pane.Markdown("## Fiber Schematic Viewer"),
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
