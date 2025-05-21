from pathlib import Path
from typing import List, Dict, Any

from aind_metadata_viz.query.database import (
    get_project_names,
)

# Datasource router
prompt_path = Path(__file__).parent / "query_constructor.txt"
prompt = prompt_path.read_text()

def get_initial_messages() -> List[Dict[str, Any]]:
    """Get the initial messages for the chat query."""
    project_names = get_project_names()
    return [
        {
            "role": "system",
            "content": [
                {
                    "type": "text",
                    "text": f"{prompt}",
                },
                {
                    "type": "text",
                    "text": f" Use this list of project names: {project_names}",
                },
                {
                    "cachePoint": {"type": "default"},
                },
            ],
        },
    ]


