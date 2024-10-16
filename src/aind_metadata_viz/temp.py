from aind_metadata_viz.metadata_helpers import *
from aind_metadata_viz.docdb import _get_all
import json
from aind_data_schema_models.modalities import (
    Modality,
    ExpectedFiles,
    FileRequirement,
)
from aind_metadata_viz.metadata_helpers import (
    process_record_list,
)
from aind_metadata_viz.metadata_class_map import (
    first_layer_field_mapping,
    second_layer_field_mappings,
)
ALL_FILES = sorted(
    [
        "data_description",
        "acquisition",
        "procedures",
        "subject",
        "instrument",
        "processing",
        "rig",
        "session",
        "quality_control",
    ]
)


# records = _get_all()

with open('data.json', 'r') as f:
    record_list = json.loads(f.read())


file_dfs = {}
# filter by file
for file in ALL_FILES:
    expected_fields = second_layer_field_mappings[file]
    # get field presence
    field_record_list = [record[file] if file in record else None for record in record_list]

    processed = process_record_list(field_record_list, expected_fields, parent=file)

    print(processed)
