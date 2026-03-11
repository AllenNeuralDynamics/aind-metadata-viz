import json
import logging
from enum import Enum

# from aind_data_schema.core.metadata import CORE_FILES  # todo: import instead of declaring

FIXED_WIDTH = 1200

# Cache TTL constants (seconds)
TTL_DAY = 24 * 60 * 60
TTL_HOUR = 60 * 60
# Aliases used in database.py
CACHE_RESET_DAY = TTL_DAY
CACHE_RESET_HOUR = TTL_HOUR


class JsonFormatter(logging.Formatter):
    """Format log records as JSON lines for structured logging."""

    _BUILTIN_ATTRS = {
        "args", "created", "exc_info", "exc_text", "filename", "funcName",
        "levelname", "levelno", "lineno", "message", "module", "msecs",
        "msg", "name", "pathname", "process", "processName",
        "relativeCreated", "stack_info", "taskName", "thread", "threadName",
    }

    def format(self, record):
        """Format a log record as a JSON string."""
        log_data = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%SZ"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_data["traceback"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key not in self._BUILTIN_ATTRS:
                log_data[key] = value
        return json.dumps(log_data)

outer_style = {
    "background": "#ffffff",
    "border-radius": "5px",
    "border": "2px solid black",
    "padding": "10px",
    "box-shadow": "5px 5px 5px #bcbcbc",
    "margin": "5px",
}

CORE_FILES = [
    "subject",
    "data_description",
    "procedures",
    "session",
    "rig",
    "processing",
    "acquisition",
    "instrument",
    "quality_control",
]


METASTATE_MAP = {
    2: "valid",
    1: "present",
    0: "optional",
    -1: "missing",
    -2: "excluded",
    -3: "corrupt",
}


class MetadataState(int, Enum):
    VALID = 2  # validates as it's class
    PRESENT = 1  # present
    OPTIONAL = 0  # missing, but it's optional
    MISSING = -1  # missing, and it's required
    EXCLUDED = -2  # excluded for all modalities in the metadata
    CORRUPT = -3  # corrupt, can't be loaded from json


REMAPS = {
    "OPHYS": "POPHYS",
    "EPHYS": "ECEPHYS",
    "TRAINED_BEHAVIOR": "BEHAVIOR",
    "HSFP": "FIB",
    "DISPIM": "SPIM",
    "MULTIPLANE_OPHYS": "POPHYS",
    "SMARTSPIM": "SPIM",
    "FIP": "FIB",
    "SINGLE_PLANE_OPHYS": "POPHYS",
    "EXASPIM": "SPIM",
}

AIND_COLORS = {
    "dark_blue": "#003057",
    "light_blue": "#2A7DE1",
    "green": "#1D8649",
    "yellow": "#FFB71B",
    "grey": "#7C7C7F",
    "red": "#FF5733",
}

COLOR_OPTIONS = {
    "default": {
        "valid": AIND_COLORS["green"],
        "present": AIND_COLORS["light_blue"],
        "optional": "grey",
        "missing": "red",
        "excluded": "#F0F0F0",
    },
    "lemonade": {
        "valid": "#F49FD7",
        "present": "#FFD966",
        "optional": "grey",
        "missing": "#9FF2F5",
        "excluded": "white",
    },
    "aind": {
        "valid": AIND_COLORS["green"],
        "present": AIND_COLORS["light_blue"],
        "optional": AIND_COLORS["grey"],
        "missing": AIND_COLORS["red"],
        "excluded": "white",
    },
}


def hd_style(text, colors):
    return (
        f"<span style='font-weight: bold; color:{colors[text]}'>{text}</span>"
    )


def sort_with_none(strings):
    """
    Sort a list of strings, placing None values at the beginning.

    Parameters:
        strings (list): A list that may contain strings and None values.

    Returns:
        list: Sorted list with None values first.
    """
    return sorted(strings, key=lambda x: (x is not None, x))
