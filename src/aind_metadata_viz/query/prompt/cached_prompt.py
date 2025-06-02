from pathlib import Path
from typing import List, Dict, Any

from aind_metadata_viz.query.database import (
    get_project_names,
    get_session_types,
    get_modalities
)

# Datasource router
prompt_path = Path(__file__).parent / "query_constructor.txt"
prompt = prompt_path.read_text()



project_names = get_project_names()

project_session_list = []
for name in project_names:
    sessions= get_session_types(name)
    project_session_list.append({"project_name": name, "sessions":sessions})

print(project_session_list)


def get_initial_messages() -> List[Dict[str, Any]]:
    """Get the initial messages for the chat query."""

    project_names = get_project_names()

    project_session_list = []
    for name in project_names:
        sessions= get_session_types(name)
        modalities= get_modalities(name)
        project_session_list.append(
            {
                "project_name": name, 
                "sessions":sessions,
                "modalities": modalities,
            }
        )

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
                    "text": (
                        "Use this list of project names,sessions and modalities:"
                        f"{project_session_list}"
                        ),
                },
                {
                    "cachePoint": {"type": "default"},
                },
            ],
        },
    ]


