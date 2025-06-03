from pathlib import Path
from typing import List, Dict, Any

from aind_metadata_viz.query.database import (
    get_project_names,
    get_session_types,
    get_modalities
)

prompt = '''
You are a neuroscientist who is expert in constructing MongoDB filters queries. 
Your main task is constructing a concise query filter that takes into account what the user is looking for. This filter will then be used to query a MongoDB database.

Key technical requirements:

ALWAYS unwind nested procedure fields (e.g., {'\$unwind': '\$procedures.subject_procedures.procedures'})
Use \$unwind for any array fields
For modality queries, access data_description.modality.name
Use \$regex instead of \$elemmatch (e.g., {"field": {"\$regex": "term", "\$options": "i"}})
Be careful with duration queries; don't use \$subtract as durations are stored as strings
Ignore created and last_modified fields as they're only metadata

Start with a simple query and refine only if necessary
If a query becomes complex, break it down into smaller sub-queries
If you detect your query approach becoming too complex, stop and recommend a simpler alternative approach

Here is a list of schemas that contains information about the structure of a JSON file.
Metadata/
├── metadata_status
├── name (name of data asset, follows specific structure <modality>_<subject_id>_<date>)
├── quality_control
├── schema_version
├── acquisition/
│   ├── describedBy: string
│   ├── schema_version: string
│   ├── protocol_id: array (DOI for protocols.io)
│   ├── experimenter_full_name*: array (First and last name of the experimenter(s))
│   ├── specimen_id*: string
│   ├── subject_id: string or null
│   ├── instrument_id*: string
│   ├── calibrations: array (List of calibration measurements taken prior to acquisition)
│   ├── maintenance: array (List of maintenance on rig prior to acquisition)
│   ├── session_start_time*: string
│   ├── session_end_time*: string
│   ├── session_type: string or null
│   ├── tiles*: array
│   ├── axes*: array
│   ├── chamber_immersion*: enum
│   ├── sample_immersion: string or null
│   ├── active_objectives: array or null
│   ├── local_storage_directory: string or null
│   ├── external_storage_directory: string or null
│   ├── processing_steps: array (List of downstream processing steps planned for each channel)
│   ├── software: object or null
│   └── notes: string or null
│
├── data_description/
│   ├── describedBy: string
│   ├── schema_version: string
│   ├── license: string
│   ├── platform*: object (Name for a standardized primary data collection system)
│   ├── subject_id*: string (Unique identifier for the subject of data acquisition)
│   ├── creation_time*: string (Time that data files were created)
│   ├── label: string or null (A short name for the data, used in file names and labels)
│   ├── name: string or null (Name of data, conventionally also the name of the directory)
│   ├── institution*: object (Organization that collected this data)
│   ├── funding_source*: array (Funding source. If internal funding, select 'Allen Institute')
│   ├── data_level*: enum (Level of processing that data has undergone)
│   ├── group: string or null (A short name for the group of individuals that collected this data)
│   ├── investigators*: array (Full name(s) of key investigators)
│   ├── project_name: string or null (A name for a set of coordinated activities)
│   ├── restrictions: string or null (Detail any restrictions on publishing or sharing these data)
│   ├── modality*: array (A short name for the specific manner of data generation)
│   ├── related_data: array (Path and description of associated data assets)
│   └── data_summary: string or null (Semantic summary of experimental goal)
│
├── instrument/
│   ├── describedBy: string
│   ├── schema_version: string
│   ├── instrument_id: string or null
│   ├── modification_date*: string
│   ├── instrument_type*: enum
│   ├── manufacturer*: object
│   ├── temperature_control: object or null
│   ├── humidity_control: object or null
│   ├── optical_tables: array
│   ├── enclosure: object or null
│   ├── objectives*: array
│   ├── detectors: array
│   ├── light_sources: array
│   ├── lenses: array
│   ├── fluorescence_filters: array
│   ├── motorized_stages: array
│   ├── scanning_stages: array
│   ├── additional_devices: array
│   ├── calibration_date: string or null
│   ├── calibration_data: string or null
│   ├── com_ports: array
│   ├── daqs: array
│   └── notes: string or null
│
├── procedures/
│   ├── describedBy: string
│   ├── schema_version: string
│   ├── subject_id*: string (Unique identifier for the subject)
│   ├── subject_procedures: array
│   ├── specimen_procedures: array
│   └── notes: string or null
│
├── processing/
│   ├── describedBy: string
│   ├── schema_version: string
│   ├── processing_pipeline*: enum (Pipeline used to process data)
│   ├── analyses: array (Analysis steps taken after processing)
│   └── notes: string or null
│
├── quality_control/
│   ├── describedBy: string
│   ├── schema_version: string
│   ├── evaluations*: array
│   └── notes: string or null
│
├── rig/
│   ├── describedBy: string
│   ├── schema_version: string
│   ├── rig_id*: string (Unique rig identifier)
│   ├── modification_date*: string
│   ├── mouse_platform*: object
│   ├── stimulus_devices: array
│   ├── cameras: array
│   ├── enclosure: object or null
│   ├── ephys_assemblies: array
│   ├── fiber_assemblies: array
│   ├── stick_microscopes: array
│   ├── laser_assemblies: array
│   ├── patch_cords: array
│   ├── light_sources: array
│   ├── detectors: array
│   ├── objectives: array
│   ├── filters: array
│   ├── lenses: array
│   ├── digital_micromirror_devices: array
│   ├── polygonal_scanners: array
│   ├── pockels_cells: array
│   ├── additional_devices: array
│   ├── daqs: array
│   ├── calibrations*: array
│   ├── ccf_coordinate_transform: string or null (Path to coordinate transform file)
│   ├── origin: object or null
│   ├── rig_axes: object or null
│   ├── modalities*: array
│   └── notes: string or null
│
├── session/
│   ├── describedBy: string
│   ├── schema_version: string
│   ├── protocol_id: array (DOI for protocols.io)
│   ├── experimenter_full_name*: array (First and last name of the experimenter(s))
│   ├── session_start_time*: string
│   ├── session_end_time: string or null
│   ├── session_type*: string
│   ├── iacuc_protocol: string or null
│   ├── rig_id*: string
│   ├── calibrations: array (Calibrations of rig devices prior to session)
│   ├── maintenance: array (Maintenance of rig devices prior to session)
│   ├── subject_id*: string
│   ├── animal_weight_prior: number or null (Animal weight before procedure)
│   ├── animal_weight_post: number or null (Animal weight after procedure)
│   ├── weight_unit: enum
│   ├── anaesthesia: object or null
│   ├── data_streams*: array (Collection of devices recorded simultaneously)
│   ├── stimulus_epochs: array
│   ├── mouse_platform_name*: string
│   ├── active_mouse_platform*: boolean (Is the mouse platform being actively controlled)
│   ├── headframe_registration: object or null (MRI transform matrix for headframe)
│   ├── reward_delivery: number or null
│   ├── reward_consumed_total: number or null
│   ├── reward_consumed_unit: enum
│   └── notes: string or null
│
└── subject/
    ├── describedBy: string
    ├── schema_version: string
    ├── subject_id*: string (Unique identifier for the subject)
    ├── sex*: enum
    ├── date_of_birth*: string
    ├── genotype: string or null (Genotype of the animal providing both alleles)
    ├── species*: object
    ├── alleles: array (Allele names and persistent IDs)
    ├── background_strain: object or null
    ├── breeding_info: object or null
    ├── source*: object (Where the subject was acquired from)
    ├── rrid: object or null (RRID of mouse if acquired from supplier)
    ├── restrictions: string or null (Any restrictions on use or publishing)
    ├── wellness_reports: array
    ├── housing: object or null
    └── notes: string or null
Note that these are only high level fields. The schema is nested and contains more fields, which you can see in the example attached below.

Here is additional information about the quality control field:
The quality_control schema defines how quality metrics are organized and evaluated for data assets:

- Each data asset has an array of "evaluations"
- Each evaluation contains:
  - modality: The type of data (SPIM, ecephys, behavior, etc.)
  - stage: When quality was assessed (Raw data, Processing, Analysis, Multi-asset)
  - metrics: Array of individual measurements with name, value, and status history
  - status: Overall Pass/Fail/Pending status of the evaluation
Important quality_control query patterns:
1. To query evaluation properties:
   {"quality_control.evaluations": {"\$elemMatch": {<conditions>}}}

2. To unwind and query individual evaluations:
   [{\$unwind: "\$quality_control.evaluations"}, {\$match: {"quality_control.evaluations.<field>": <value>}}]

3. To query metrics within evaluations:
   [{\$unwind: "\$quality_control.evaluations"}, 
    {\$unwind: "\$quality_control.evaluations.metrics"},
    {\$match: {"quality_control.evaluations.metrics.name": <metric_name>}}]

Example queries:
- Find assets with failed quality control evaluations: 
  {"quality_control.evaluations.latest_status": "Fail"}
- Find SPIM data with pending QC: 
  {"quality_control.evaluations": {"\$elemMatch": {"modality.abbreviation": "SPIM", "latest_status": "Pending"}}}
- Count metrics per evaluation: 
  {\$project: {"metricCount": {\$size: "\$quality_control.evaluations.metrics"}}}

Here is a sample, filled out metadata schema. It may contain missing information but serves as a reference to what a metadata file looks like.
You can use it as a guide to better structure your queries.
Sample metadata: [[{
  "_id": "d88c355a-f3ea-4f75-879f-9dca358ec5bb",
  "acquisition": {
    "active_objectives": null,
    "axes": [
      {
        "dimension": 2,
        "direction": "Left_to_right",
        "name": "X",
        "unit": "micrometer"
      },
      {
        "dimension": 1,
        "direction": "Posterior_to_anterior",
        "name": "Y",
        "unit": "micrometer"
      },
      {
        "dimension": 0,
        "direction": "Superior_to_inferior",
        "name": "Z",
        "unit": "micrometer"
      }
    ],
    "chamber_immersion": {
      "medium": "Cargille oil",
      "refractive_index": 1.5208
    },
    "describedBy": "https://raw.githubusercontent.com/AllenNeuralDynamics/aind-data-schema/main/src/aind_data_schema/imaging/acquisition.py",
    "experimenter_full_name": "John Rohde",
    "external_storage_directory": "",
    "instrument_id": "SmartSPIM1-1",
    "local_storage_directory": "D:",
    "sample_immersion": null,
    "schema_version": "0.4.2",
    "session_end_time": "2023-03-06T22:59:16",
    "session_start_time": "2023-03-06T17:47:13",
    "specimen_id": "",
    "subject_id": "662616",
    "tiles": [
      {
        "channel": {
          "channel_name": "445.0",
          "filter_wheel_index": 0,
          "laser_power": 30,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 445,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              42033,
              41585,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_445_Em_469/420330/420330_415850/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "488.0",
          "filter_wheel_index": 1,
          "laser_power": 20,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 488,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              42033,
              41585,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_488_Em_525/420330/420330_415850/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "561.0",
          "filter_wheel_index": 2,
          "laser_power": 25,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 561,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              42033,
              41585,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_561_Em_593/420330/420330_415850/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "445.0",
          "filter_wheel_index": 0,
          "laser_power": 30,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 445,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              45273,
              41585,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_445_Em_469/452730/452730_415850/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "488.0",
          "filter_wheel_index": 1,
          "laser_power": 20,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 488,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              45273,
              41585,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_488_Em_525/452730/452730_415850/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "561.0",
          "filter_wheel_index": 2,
          "laser_power": 25,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 561,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              45273,
              41585,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_561_Em_593/452730/452730_415850/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "445.0",
          "filter_wheel_index": 0,
          "laser_power": 30,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 445,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              48513,
              41585,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_445_Em_469/485130/485130_415850/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "488.0",
          "filter_wheel_index": 1,
          "laser_power": 20,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 488,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              48513,
              41585,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_488_Em_525/485130/485130_415850/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "561.0",
          "filter_wheel_index": 2,
          "laser_power": 25,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 561,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              48513,
              41585,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_561_Em_593/485130/485130_415850/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "445.0",
          "filter_wheel_index": 0,
          "laser_power": 30,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 445,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              51753,
              41585,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_445_Em_469/517530/517530_415850/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "488.0",
          "filter_wheel_index": 1,
          "laser_power": 20,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 488,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              51753,
              41585,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_488_Em_525/517530/517530_415850/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "561.0",
          "filter_wheel_index": 2,
          "laser_power": 25,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 561,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              51753,
              41585,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_561_Em_593/517530/517530_415850/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "445.0",
          "filter_wheel_index": 0,
          "laser_power": 30,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 445,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              42033,
              44177,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_445_Em_469/420330/420330_441770/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "488.0",
          "filter_wheel_index": 1,
          "laser_power": 20,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 488,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              42033,
              44177,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_488_Em_525/420330/420330_441770/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "561.0",
          "filter_wheel_index": 2,
          "laser_power": 25,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 561,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              42033,
              44177,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_561_Em_593/420330/420330_441770/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "445.0",
          "filter_wheel_index": 0,
          "laser_power": 30,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 445,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              45273,
              44177,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_445_Em_469/452730/452730_441770/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "488.0",
          "filter_wheel_index": 1,
          "laser_power": 20,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 488,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              45273,
              44177,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_488_Em_525/452730/452730_441770/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "561.0",
          "filter_wheel_index": 2,
          "laser_power": 25,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 561,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              45273,
              44177,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_561_Em_593/452730/452730_441770/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "445.0",
          "filter_wheel_index": 0,
          "laser_power": 30,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 445,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              48513,
              44177,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_445_Em_469/485130/485130_441770/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "488.0",
          "filter_wheel_index": 1,
          "laser_power": 20,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 488,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              48513,
              44177,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_488_Em_525/485130/485130_441770/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "561.0",
          "filter_wheel_index": 2,
          "laser_power": 25,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 561,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              48513,
              44177,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_561_Em_593/485130/485130_441770/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "445.0",
          "filter_wheel_index": 0,
          "laser_power": 30,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 445,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              51753,
              44177,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_445_Em_469/517530/517530_441770/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "488.0",
          "filter_wheel_index": 1,
          "laser_power": 20,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 488,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              51753,
              44177,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_488_Em_525/517530/517530_441770/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "561.0",
          "filter_wheel_index": 2,
          "laser_power": 25,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 561,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              51753,
              44177,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_561_Em_593/517530/517530_441770/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "445.0",
          "filter_wheel_index": 0,
          "laser_power": 30,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 445,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              42033,
              46769,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_445_Em_469/420330/420330_467690/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "488.0",
          "filter_wheel_index": 1,
          "laser_power": 20,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 488,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              42033,
              46769,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_488_Em_525/420330/420330_467690/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "561.0",
          "filter_wheel_index": 2,
          "laser_power": 25,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 561,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              42033,
              46769,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_561_Em_593/420330/420330_467690/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "445.0",
          "filter_wheel_index": 0,
          "laser_power": 30,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 445,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              45273,
              46769,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_445_Em_469/452730/452730_467690/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "488.0",
          "filter_wheel_index": 1,
          "laser_power": 20,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 488,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              45273,
              46769,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_488_Em_525/452730/452730_467690/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "561.0",
          "filter_wheel_index": 2,
          "laser_power": 25,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 561,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              45273,
              46769,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_561_Em_593/452730/452730_467690/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "445.0",
          "filter_wheel_index": 0,
          "laser_power": 30,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 445,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              48513,
              46769,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_445_Em_469/485130/485130_467690/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "488.0",
          "filter_wheel_index": 1,
          "laser_power": 20,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 488,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              48513,
              46769,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_488_Em_525/485130/485130_467690/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "561.0",
          "filter_wheel_index": 2,
          "laser_power": 25,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 561,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              48513,
              46769,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_561_Em_593/485130/485130_467690/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "445.0",
          "filter_wheel_index": 0,
          "laser_power": 30,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 445,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              51753,
              46769,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_445_Em_469/517530/517530_467690/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "488.0",
          "filter_wheel_index": 1,
          "laser_power": 20,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 488,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              51753,
              46769,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_488_Em_525/517530/517530_467690/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "561.0",
          "filter_wheel_index": 2,
          "laser_power": 25,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 561,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              51753,
              46769,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_561_Em_593/517530/517530_467690/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "445.0",
          "filter_wheel_index": 0,
          "laser_power": 30,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 445,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              42033,
              49361,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_445_Em_469/420330/420330_493610/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "488.0",
          "filter_wheel_index": 1,
          "laser_power": 20,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 488,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              42033,
              49361,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_488_Em_525/420330/420330_493610/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "561.0",
          "filter_wheel_index": 2,
          "laser_power": 25,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 561,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              42033,
              49361,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_561_Em_593/420330/420330_493610/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "445.0",
          "filter_wheel_index": 0,
          "laser_power": 30,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 445,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              45273,
              49361,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_445_Em_469/452730/452730_493610/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "488.0",
          "filter_wheel_index": 1,
          "laser_power": 20,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 488,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              45273,
              49361,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_488_Em_525/452730/452730_493610/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "561.0",
          "filter_wheel_index": 2,
          "laser_power": 25,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 561,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              45273,
              49361,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_561_Em_593/452730/452730_493610/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "445.0",
          "filter_wheel_index": 0,
          "laser_power": 30,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 445,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              48513,
              49361,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_445_Em_469/485130/485130_493610/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "488.0",
          "filter_wheel_index": 1,
          "laser_power": 20,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 488,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              48513,
              49361,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_488_Em_525/485130/485130_493610/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "561.0",
          "filter_wheel_index": 2,
          "laser_power": 25,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 561,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              48513,
              49361,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_561_Em_593/485130/485130_493610/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "445.0",
          "filter_wheel_index": 0,
          "laser_power": 30,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 445,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              51753,
              49361,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_445_Em_469/517530/517530_493610/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "488.0",
          "filter_wheel_index": 1,
          "laser_power": 20,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 488,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              51753,
              49361,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_488_Em_525/517530/517530_493610/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "561.0",
          "filter_wheel_index": 2,
          "laser_power": 25,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 561,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              51753,
              49361,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_561_Em_593/517530/517530_493610/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "445.0",
          "filter_wheel_index": 0,
          "laser_power": 30,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 445,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              42033,
              51953,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_445_Em_469/420330/420330_519530/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "488.0",
          "filter_wheel_index": 1,
          "laser_power": 20,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 488,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              42033,
              51953,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_488_Em_525/420330/420330_519530/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "561.0",
          "filter_wheel_index": 2,
          "laser_power": 25,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 561,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              42033,
              51953,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_561_Em_593/420330/420330_519530/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "445.0",
          "filter_wheel_index": 0,
          "laser_power": 30,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 445,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              45273,
              51953,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_445_Em_469/452730/452730_519530/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "488.0",
          "filter_wheel_index": 1,
          "laser_power": 20,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 488,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              45273,
              51953,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_488_Em_525/452730/452730_519530/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "561.0",
          "filter_wheel_index": 2,
          "laser_power": 25,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 561,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              45273,
              51953,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_561_Em_593/452730/452730_519530/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "445.0",
          "filter_wheel_index": 0,
          "laser_power": 30,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 445,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              48513,
              51953,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_445_Em_469/485130/485130_519530/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "488.0",
          "filter_wheel_index": 1,
          "laser_power": 20,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 488,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              48513,
              51953,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_488_Em_525/485130/485130_519530/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "561.0",
          "filter_wheel_index": 2,
          "laser_power": 25,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 561,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              48513,
              51953,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_561_Em_593/485130/485130_519530/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "445.0",
          "filter_wheel_index": 0,
          "laser_power": 30,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 445,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              51753,
              51953,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_445_Em_469/517530/517530_519530/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "488.0",
          "filter_wheel_index": 1,
          "laser_power": 20,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 488,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              51753,
              51953,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_488_Em_525/517530/517530_519530/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "561.0",
          "filter_wheel_index": 2,
          "laser_power": 25,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 561,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              51753,
              51953,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_561_Em_593/517530/517530_519530/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "445.0",
          "filter_wheel_index": 0,
          "laser_power": 30,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 445,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              42033,
              54545,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_445_Em_469/420330/420330_545450/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "488.0",
          "filter_wheel_index": 1,
          "laser_power": 20,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 488,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              42033,
              54545,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_488_Em_525/420330/420330_545450/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "561.0",
          "filter_wheel_index": 2,
          "laser_power": 25,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 561,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              42033,
              54545,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_561_Em_593/420330/420330_545450/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "445.0",
          "filter_wheel_index": 0,
          "laser_power": 30,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 445,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              45273,
              54545,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_445_Em_469/452730/452730_545450/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "488.0",
          "filter_wheel_index": 1,
          "laser_power": 20,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 488,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              45273,
              54545,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_488_Em_525/452730/452730_545450/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "561.0",
          "filter_wheel_index": 2,
          "laser_power": 25,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 561,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              45273,
              54545,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_561_Em_593/452730/452730_545450/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "445.0",
          "filter_wheel_index": 0,
          "laser_power": 30,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 445,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              48513,
              54545,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_445_Em_469/485130/485130_545450/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "488.0",
          "filter_wheel_index": 1,
          "laser_power": 20,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 488,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              48513,
              54545,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_488_Em_525/485130/485130_545450/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "561.0",
          "filter_wheel_index": 2,
          "laser_power": 25,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 561,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              48513,
              54545,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_561_Em_593/485130/485130_545450/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "445.0",
          "filter_wheel_index": 0,
          "laser_power": 30,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 445,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              51753,
              54545,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_445_Em_469/517530/517530_545450/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "488.0",
          "filter_wheel_index": 1,
          "laser_power": 20,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 488,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              51753,
              54545,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_488_Em_525/517530/517530_545450/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "561.0",
          "filter_wheel_index": 2,
          "laser_power": 25,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 561,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              51753,
              54545,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_561_Em_593/517530/517530_545450/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "445.0",
          "filter_wheel_index": 0,
          "laser_power": 30,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 445,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              42033,
              57137,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_445_Em_469/420330/420330_571370/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "488.0",
          "filter_wheel_index": 1,
          "laser_power": 20,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 488,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              42033,
              57137,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_488_Em_525/420330/420330_571370/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "561.0",
          "filter_wheel_index": 2,
          "laser_power": 25,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 561,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              42033,
              57137,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_561_Em_593/420330/420330_571370/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "445.0",
          "filter_wheel_index": 0,
          "laser_power": 30,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 445,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              45273,
              57137,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_445_Em_469/452730/452730_571370/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "488.0",
          "filter_wheel_index": 1,
          "laser_power": 20,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 488,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              45273,
              57137,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_488_Em_525/452730/452730_571370/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "561.0",
          "filter_wheel_index": 2,
          "laser_power": 25,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 561,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              45273,
              57137,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_561_Em_593/452730/452730_571370/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "445.0",
          "filter_wheel_index": 0,
          "laser_power": 30,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 445,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              48513,
              57137,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_445_Em_469/485130/485130_571370/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "488.0",
          "filter_wheel_index": 1,
          "laser_power": 20,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 488,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              48513,
              57137,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_488_Em_525/485130/485130_571370/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "561.0",
          "filter_wheel_index": 2,
          "laser_power": 25,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 561,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              48513,
              57137,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_561_Em_593/485130/485130_571370/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "445.0",
          "filter_wheel_index": 0,
          "laser_power": 30,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 445,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              51753,
              57137,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_445_Em_469/517530/517530_571370/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "488.0",
          "filter_wheel_index": 1,
          "laser_power": 20,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 488,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              51753,
              57137,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_488_Em_525/517530/517530_571370/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      },
      {
        "channel": {
          "channel_name": "561.0",
          "filter_wheel_index": 2,
          "laser_power": 25,
          "laser_power_unit": "milliwatt",
          "laser_wavelength": 561,
          "laser_wavelength_unit": "nanometer"
        },
        "coordinate_transformations": [
          {
            "translation": [
              51753,
              57137,
              10.8
            ],
            "type": "translation"
          },
          {
            "scale": [
              1.8,
              1.8,
              2
            ],
            "type": "scale"
          }
        ],
        "file_name": "Ex_561_Em_593/517530/517530_571370/",
        "imaging_angle": 0,
        "imaging_angle_unit": "degree",
        "notes": "\nLaser power is in percentage of total -- needs calibration"
      }
    ]
  },
  "created": "2024-06-20T21:02:37.011333",
  "data_description": {
    "describedBy": "https://raw.githubusercontent.com/AllenNeuralDynamics/aind-data-schema/main/src/aind_data_schema/core/data_description.py",
    "schema_version": "1.0.0",
    "license": "CC-BY-4.0",
    "platform": {
      "name": "SmartSPIM platform",
      "abbreviation": "SmartSPIM"
    },
    "subject_id": "662616",
    "creation_time": "2023-04-14T15:11:04-07:00",
    "label": null,
    "name": "SmartSPIM_662616_2023-04-14_15-11-04",
    "institution": {
      "name": "Allen Institute for Neural Dynamics",
      "abbreviation": "AIND",
      "registry": {
        "name": "Research Organization Registry",
        "abbreviation": "ROR"
      },
      "registry_identifier": "04szwah67"
    },
    "funding_source": [
      {
        "funder": {
          "name": "National Institute of Neurological Disorders and Stroke",
          "abbreviation": "NINDS",
          "registry": {
            "name": "Research Organization Registry",
            "abbreviation": "ROR"
          },
          "registry_identifier": "01s5ya894"
        },
        "grant_number": "NIH1U19NS123714-01",
        "fundee": "Jayaram Chandreashekar, Mathew Summers"
      }
    ],
    "data_level": "raw",
    "group": "MSMA",
    "investigators": [
      {
        "name": "Mathew Summers",
        "abbreviation": null,
        "registry": null,
        "registry_identifier": null
      },
      {
        "name": "Jayaram Chandrashekar",
        "abbreviation": null,
        "registry": null,
        "registry_identifier": null
      }
    ],
    "project_name": "Thalamus in the middle",
    "restrictions": null,
    "modality": [
      {
        "name": "Selective plane illumination microscopy",
        "abbreviation": "SPIM"
      }
    ],
    "related_data": [],
    "data_summary": null
  },
  "describedBy": "https://raw.githubusercontent.com/AllenNeuralDynamics/aind-data-schema/main/src/aind_data_schema/core/metadata.py",
  "external_links": {
    "Code Ocean": [
      "97189da9-88ea-4d85-b1b0-ceefb9299f1a"
    ]
  },
  "instrument": {
    "describedBy": "https://raw.githubusercontent.com/AllenNeuralDynamics/aind-data-schema/main/src/aind_data_schema/imaging/instrument.py",
    "schema_version": "0.5.4",
    "instrument_id": "SmartSPIM1-2",
    "instrument_type": "SmartSPIM",
    "location": "615 Westlake",
    "manufacturer": "LifeCanvas",
    "temperature_control": true,
    "humidity_control": false,
    "optical_tables": [
      {
        "name": null,
        "serial_number": "Unknown",
        "manufacturer": "MKS Newport",
        "model": "VIS3648-PG4-325A",
        "notes": null,
        "length": 36,
        "width": 48,
        "table_size_unit": "inch",
        "vibration_control": true
      }
    ],
    "objectives": [
      {
        "name": null,
        "serial_number": "Unknown",
        "manufacturer": "Thorlabs",
        "model": "TL2X-SAP",
        "notes": "",
        "numerical_aperture": 0.1,
        "magnification": 1.6,
        "immersion": "multi"
      },
      {
        "name": null,
        "serial_number": "Unknown",
        "manufacturer": "Thorlabs",
        "model": "TL4X-SAP",
        "notes": "Thorlabs TL4X-SAP with LifeCanvas dipping cap and correction optics",
        "numerical_aperture": 0.2,
        "magnification": 3.6,
        "immersion": "multi"
      },
      {
        "name": null,
        "serial_number": "Unknown",
        "manufacturer": "Nikon",
        "model": "MRP07220",
        "notes": "",
        "numerical_aperture": 0.8,
        "magnification": 16,
        "immersion": "water"
      },
      {
        "name": null,
        "serial_number": "Unknown",
        "manufacturer": "Nikon",
        "model": "MRD77220",
        "notes": "",
        "numerical_aperture": 1.1,
        "magnification": 25,
        "immersion": "water"
      }
    ],
    "detectors": [
      {
        "name": null,
        "serial_number": "220302-SYS-060443",
        "manufacturer": "Hamamatsu",
        "model": "C14440-20UP",
        "notes": null,
        "type": "Camera",
        "data_interface": "USB",
        "cooling": "water"
      }
    ],
    "light_sources": [
      {
        "name": null,
        "serial_number": "VL08223M03",
        "manufacturer": "Vortran",
        "model": "Stradus",
        "notes": "All lasers controlled via Vortran VersaLase System",
        "type": "laser",
        "coupling": "Single-mode fiber",
        "wavelength": 445,
        "wavelength_unit": "nanometer",
        "max_power": 150,
        "power_unit": "milliwatt"
      },
      {
        "name": null,
        "serial_number": "VL08223M03",
        "manufacturer": "Vortran",
        "model": "Stradus",
        "notes": "All lasers controlled via Vortran VersaLase System",
        "type": "laser",
        "coupling": "Single-mode fiber",
        "wavelength": 488,
        "wavelength_unit": "nanometer",
        "max_power": 150,
        "power_unit": "milliwatt"
      },
      {
        "name": null,
        "serial_number": "VL08223M03",
        "manufacturer": "Vortran",
        "model": "Stradus",
        "notes": "All lasers controlled via Vortran VersaLase System",
        "type": "laser",
        "coupling": "Single-mode fiber",
        "wavelength": 561,
        "wavelength_unit": "nanometer",
        "max_power": 150,
        "power_unit": "milliwatt"
      },
      {
        "name": null,
        "serial_number": "VL08223M03",
        "manufacturer": "Vortran",
        "model": "Stradus",
        "notes": "All lasers controlled via Vortran VersaLase System",
        "type": "laser",
        "coupling": "Single-mode fiber",
        "wavelength": 594,
        "wavelength_unit": "nanometer",
        "max_power": 150,
        "power_unit": "milliwatt"
      },
      {
        "name": null,
        "serial_number": "VL08223M03",
        "manufacturer": "Vortran",
        "model": "Stradus",
        "notes": "All lasers controlled via Vortran VersaLase System",
        "type": "laser",
        "coupling": "Single-mode fiber",
        "wavelength": 639,
        "wavelength_unit": "nanometer",
        "max_power": 160,
        "power_unit": "milliwatt"
      },
      {
        "name": null,
        "serial_number": "VL08223M03",
        "manufacturer": "Vortran",
        "model": "Stradus",
        "notes": "All lasers controlled via Vortran VersaLase System",
        "type": "laser",
        "coupling": "Single-mode fiber",
        "wavelength": 665,
        "wavelength_unit": "nanometer",
        "max_power": 160,
        "power_unit": "milliwatt"
      }
    ],
    "fluorescence_filters": [
      {
        "name": null,
        "serial_number": "Unknown-0",
        "manufacturer": "Semrock",
        "model": "FF01-469/35-25",
        "notes": null,
        "filter_type": "Band pass",
        "diameter": 25,
        "diameter_unit": "millimeter",
        "thickness": 2,
        "thickness_unit": "millimeter",
        "filter_wheel_index": 0,
        "cut_off_frequency": null,
        "cut_off_frequency_unit": "Hertz",
        "cut_on_frequency": null,
        "cut_on_frequency_unit": "Hertz",
        "description": null
      },
      {
        "name": null,
        "serial_number": "Unknown-1",
        "manufacturer": "Semrock",
        "model": "FF01-525/45-25",
        "notes": null,
        "filter_type": "Band pass",
        "diameter": 25,
        "diameter_unit": "millimeter",
        "thickness": 2,
        "thickness_unit": "millimeter",
        "filter_wheel_index": 1,
        "cut_off_frequency": null,
        "cut_off_frequency_unit": "Hertz",
        "cut_on_frequency": null,
        "cut_on_frequency_unit": "Hertz",
        "description": null
      },
      {
        "name": null,
        "serial_number": "Unknown-2",
        "manufacturer": "Semrock",
        "model": "FF01-593/40-25",
        "notes": null,
        "filter_type": "Band pass",
        "diameter": 25,
        "diameter_unit": "millimeter",
        "thickness": 2,
        "thickness_unit": "millimeter",
        "filter_wheel_index": 2,
        "cut_off_frequency": null,
        "cut_off_frequency_unit": "Hertz",
        "cut_on_frequency": null,
        "cut_on_frequency_unit": "Hertz",
        "description": null
      },
      {
        "name": null,
        "serial_number": "Unknown-3",
        "manufacturer": "Semrock",
        "model": "FF01-624/40-25",
        "notes": null,
        "filter_type": "Band pass",
        "diameter": 25,
        "diameter_unit": "millimeter",
        "thickness": 2,
        "thickness_unit": "millimeter",
        "filter_wheel_index": 3,
        "cut_off_frequency": null,
        "cut_off_frequency_unit": "Hertz",
        "cut_on_frequency": null,
        "cut_on_frequency_unit": "Hertz",
        "description": null
      },
      {
        "name": null,
        "serial_number": "Unknown-4",
        "manufacturer": "Chroma",
        "model": "ET667/30m",
        "notes": null,
        "filter_type": "Band pass",
        "diameter": 25,
        "diameter_unit": "millimeter",
        "thickness": 2,
        "thickness_unit": "millimeter",
        "filter_wheel_index": 4,
        "cut_off_frequency": null,
        "cut_off_frequency_unit": "Hertz",
        "cut_on_frequency": null,
        "cut_on_frequency_unit": "Hertz",
        "description": null
      },
      {
        "name": null,
        "serial_number": "Unknown-5",
        "manufacturer": "Thorlabs",
        "model": "FELH0700",
        "notes": null,
        "filter_type": "Long pass",
        "diameter": 25,
        "diameter_unit": "millimeter",
        "thickness": 2,
        "thickness_unit": "millimeter",
        "filter_wheel_index": 5,
        "cut_off_frequency": null,
        "cut_off_frequency_unit": "Hertz",
        "cut_on_frequency": null,
        "cut_on_frequency_unit": "Hertz",
        "description": null
      }
    ],
    "motorized_stages": [
      {
        "name": null,
        "serial_number": "Unknown-0",
        "manufacturer": "Applied Scientific Instrumentation",
        "model": "LS-100",
        "notes": "Focus stage",
        "travel": 100,
        "travel_unit": "millimeter"
      },
      {
        "name": null,
        "serial_number": "Unknown-1",
        "manufacturer": "IR Robot Co",
        "model": "L12-20F-4",
        "notes": "Cylindrical lens #1",
        "travel": 41,
        "travel_unit": "millimeter"
      },
      {
        "name": null,
        "serial_number": "Unknown-2",
        "manufacturer": "IR Robot Co",
        "model": "L12-20F-4",
        "notes": "Cylindrical lens #2",
        "travel": 41,
        "travel_unit": "millimeter"
      },
      {
        "name": null,
        "serial_number": "Unknown-3",
        "manufacturer": "IR Robot Co",
        "model": "L12-20F-4",
        "notes": "Cylindrical lens #3",
        "travel": 41,
        "travel_unit": "millimeter"
      },
      {
        "name": null,
        "serial_number": "Unknown-4",
        "manufacturer": "IR Robot Co",
        "model": "L12-20F-4",
        "notes": "Cylindrical lens #4",
        "travel": 41,
        "travel_unit": "millimeter"
      }
    ],
    "scanning_stages": [
      {
        "name": null,
        "serial_number": "Unknown-0",
        "manufacturer": "Applied Scientific Instrumentation",
        "model": "LS-50",
        "notes": "Sample stage Z",
        "travel": 50,
        "travel_unit": "millimeter",
        "stage_axis_direction": "Detection axis",
        "stage_axis_name": "Z"
      },
      {
        "name": null,
        "serial_number": "Unknown-1",
        "manufacturer": "Applied Scientific Instrumentation",
        "model": "LS-50",
        "notes": "Sample stage X",
        "travel": 50,
        "travel_unit": "millimeter",
        "stage_axis_direction": "Illumination axis",
        "stage_axis_name": "X"
      },
      {
        "name": null,
        "serial_number": "Unknown-2",
        "manufacturer": "Applied Scientific Instrumentation",
        "model": "LS-50",
        "notes": "Sample stage Y",
        "travel": 50,
        "travel_unit": "millimeter",
        "stage_axis_direction": "Perpendicular axis",
        "stage_axis_name": "Y"
      }
    ],
    "daqs": null,
    "additional_devices": [
      {
        "name": null,
        "serial_number": "10436130",
        "manufacturer": "Julabo",
        "model": "200F",
        "notes": null,
        "type": "Other"
      }
    ],
    "calibration_date": null,
    "calibration_data": null,
    "com_ports": [
      {
        "hardware_name": "Laser Launch",
        "com_port": "COM3"
      },
      {
        "hardware_name": "ASI Tiger",
        "com_port": "COM5"
      },
      {
        "hardware_name": "MightyZap",
        "com_port": "COM10"
      }
    ],
    "notes": null
  },
  "last_modified": "2024-09-23T20:30:53.461182",
  "location": "s3://aind-open-data/SmartSPIM_662616_2023-03-06_17-47-13",
  "metadata_status": "Unknown",
  "name": "SmartSPIM_662616_2023-03-06_17-47-13",
  "procedures": {
    "describedBy": "https://raw.githubusercontent.com/AllenNeuralDynamics/aind-data-schema/main/src/aind_data_schema/core/procedures.py",
    "schema_version": "0.11.2",
    "subject_id": "662616",
    "subject_procedures": [
      {
        "procedure_type": "Surgery",
        "start_date": "2023-02-03",
        "experimenter_full_name": "30509",
        "iacuc_protocol": null,
        "animal_weight_prior": null,
        "animal_weight_post": null,
        "weight_unit": "gram",
        "anaesthesia": null,
        "workstation_id": null,
        "procedures": [
          {
            "procedure_type": "Perfusion",
            "protocol_id": "dx.doi.org/10.17504/protocols.io.bg5vjy66",
            "output_specimen_ids": [
              "662616"
            ]
          }
        ],
        "notes": null
      },
      {
        "procedure_type": "Surgery",
        "start_date": "2023-01-05",
        "experimenter_full_name": "NSB-5756",
        "iacuc_protocol": "2109",
        "animal_weight_prior": "16.6",
        "animal_weight_post": "16.7",
        "weight_unit": "gram",
        "anaesthesia": {
          "type": "isoflurane",
          "duration": "120.0",
          "duration_unit": "minute",
          "level": "1.5"
        },
        "workstation_id": "SWS 1",
        "procedures": [
          {
            "injection_materials": [
              {
                "material_type": "Virus",
                "name": "SL1-hSyn-Cre",
                "tars_identifiers": {
                  "virus_tars_id": null,
                  "plasmid_tars_alias": null,
                  "prep_lot_number": "221118-11",
                  "prep_date": null,
                  "prep_type": null,
                  "prep_protocol": null
                },
                "addgene_id": null,
                "titer": {
                  "$numberLong": "37500000000000"
                },
                "titer_unit": "gc/mL"
              },
              {
                "material_type": "Virus",
                "name": "AAV1-CAG-H2B-mTurquoise2-WPRE",
                "tars_identifiers": {
                  "virus_tars_id": null,
                  "plasmid_tars_alias": null,
                  "prep_lot_number": "221118-4",
                  "prep_date": null,
                  "prep_type": null,
                  "prep_protocol": null
                },
                "addgene_id": null,
                "titer": {
                  "$numberLong": "15000000000000"
                },
                "titer_unit": "gc/mL"
              }
            ],
            "recovery_time": "10.0",
            "recovery_time_unit": "minute",
            "injection_duration": null,
            "injection_duration_unit": "minute",
            "instrument_id": "NJ#2",
            "protocol_id": "dx.doi.org/10.17504/protocols.io.bgpujvnw",
            "injection_coordinate_ml": "0.35",
            "injection_coordinate_ap": "2.2",
            "injection_coordinate_depth": [
              "2.1"
            ],
            "injection_coordinate_unit": "millimeter",
            "injection_coordinate_reference": "Bregma",
            "bregma_to_lambda_distance": "4.362",
            "bregma_to_lambda_unit": "millimeter",
            "injection_angle": "0",
            "injection_angle_unit": "degrees",
            "targeted_structure": "mPFC",
            "injection_hemisphere": "Right",
            "procedure_type": "Nanoject injection",
            "injection_volume": [
              "200"
            ],
            "injection_volume_unit": "nanoliter"
          },
          {
            "injection_materials": [
              {
                "material_type": "Virus",
                "name": "AAV-Syn-DIO-TVA66T-dTomato-CVS N2cG",
                "tars_identifiers": {
                  "virus_tars_id": null,
                  "plasmid_tars_alias": null,
                  "prep_lot_number": "220916-4",
                  "prep_date": null,
                  "prep_type": null,
                  "prep_protocol": null
                },
                "addgene_id": null,
                "titer": {
                  "$numberLong": "18000000000000"
                },
                "titer_unit": "gc/mL"
              }
            ],
            "recovery_time": "10.0",
            "recovery_time_unit": "minute",
            "injection_duration": null,
            "injection_duration_unit": "minute",
            "instrument_id": "NJ#2",
            "protocol_id": "dx.doi.org/10.17504/protocols.io.bgpujvnw",
            "injection_coordinate_ml": "2.9",
            "injection_coordinate_ap": "-0.6",
            "injection_coordinate_depth": [
              "3.6"
            ],
            "injection_coordinate_unit": "millimeter",
            "injection_coordinate_reference": "Bregma",
            "bregma_to_lambda_distance": "4.362",
            "bregma_to_lambda_unit": "millimeter",
            "injection_angle": "30",
            "injection_angle_unit": "degrees",
            "targeted_structure": "VM",
            "injection_hemisphere": "Right",
            "procedure_type": "Nanoject injection",
            "injection_volume": [
              "200"
            ],
            "injection_volume_unit": "nanoliter"
          }
        ],
        "notes": null
      },
      {
        "procedure_type": "Surgery",
        "start_date": "2023-01-25",
        "experimenter_full_name": "NSB-5756",
        "iacuc_protocol": "2109",
        "animal_weight_prior": "18.6",
        "animal_weight_post": "18.7",
        "weight_unit": "gram",
        "anaesthesia": {
          "type": "isoflurane",
          "duration": "45.0",
          "duration_unit": "minute",
          "level": "1.5"
        },
        "workstation_id": "SWS 5",
        "procedures": [
          {
            "injection_materials": [
              {
                "material_type": "Virus",
                "name": "EnvA CVS-N2C-histone-GFP",
                "tars_identifiers": {
                  "virus_tars_id": null,
                  "plasmid_tars_alias": null,
                  "prep_lot_number": "221110",
                  "prep_date": null,
                  "prep_type": null,
                  "prep_protocol": null
                },
                "addgene_id": null,
                "titer": {
                  "$numberLong": "10700000000"
                },
                "titer_unit": "gc/mL"
              }
            ],
            "recovery_time": "10.0",
            "recovery_time_unit": "minute",
            "injection_duration": null,
            "injection_duration_unit": "minute",
            "instrument_id": "NJ#5",
            "protocol_id": "dx.doi.org/10.17504/protocols.io.bgpujvnw",
            "injection_coordinate_ml": "2.9",
            "injection_coordinate_ap": "-0.6",
            "injection_coordinate_depth": [
              "3.6"
            ],
            "injection_coordinate_unit": "millimeter",
            "injection_coordinate_reference": "Bregma",
            "bregma_to_lambda_distance": "4.362",
            "bregma_to_lambda_unit": "millimeter",
            "injection_angle": "30",
            "injection_angle_unit": "degrees",
            "targeted_structure": "VM",
            "injection_hemisphere": "Right",
            "procedure_type": "Nanoject injection",
            "injection_volume": [
              "200"
            ],
            "injection_volume_unit": "nanoliter"
          }
        ],
        "notes": null
      }
    ],
    "specimen_procedures": [
      {
        "procedure_type": "Fixation",
        "procedure_name": "SHIELD OFF",
        "specimen_id": "662616",
        "start_date": "2023-02-10",
        "end_date": "2023-02-12",
        "experimenter_full_name": "DT",
        "protocol_id": "none",
        "reagents": [
          {
            "name": "SHIELD Epoxy",
            "source": "LiveCanvas Technologies",
            "rrid": null,
            "lot_number": "unknown",
            "expiration_date": null
          },
          {
            "name": "SHIELD Buffer",
            "source": "LiveCanvas Technologies",
            "rrid": null,
            "lot_number": "unknown",
            "expiration_date": null
          }
        ],
        "hcr_series": null,
        "immunolabeling": null,
        "notes": "None"
      },
      {
        "procedure_type": "Fixation",
        "procedure_name": "SHIELD ON",
        "specimen_id": "662616",
        "start_date": "2023-02-12",
        "end_date": "2023-02-13",
        "experimenter_full_name": "DT",
        "protocol_id": "none",
        "reagents": [
          {
            "name": "SHIELD ON",
            "source": "LiveCanvas Technologies",
            "rrid": null,
            "lot_number": "unknown",
            "expiration_date": null
          }
        ],
        "hcr_series": null,
        "immunolabeling": null,
        "notes": "None"
      },
      {
        "procedure_type": "Delipidation",
        "procedure_name": "24h Delipidation",
        "specimen_id": "662616",
        "start_date": "2023-02-15",
        "end_date": "2023-02-16",
        "experimenter_full_name": "DT",
        "protocol_id": "none",
        "reagents": [
          {
            "name": "Delipidation Buffer",
            "source": "LiveCanvas Technologies",
            "rrid": null,
            "lot_number": "unknown",
            "expiration_date": null
          }
        ],
        "hcr_series": null,
        "immunolabeling": null,
        "notes": "None"
      },
      {
        "procedure_type": "Delipidation",
        "procedure_name": "Active Delipidation",
        "specimen_id": "662616",
        "start_date": "2023-02-16",
        "end_date": "2023-02-18",
        "experimenter_full_name": "DT",
        "protocol_id": "none",
        "reagents": [
          {
            "name": "Conduction Buffer",
            "source": "LiveCanvas Technologies",
            "rrid": null,
            "lot_number": "unknown",
            "expiration_date": null
          }
        ],
        "hcr_series": null,
        "immunolabeling": null,
        "notes": "None"
      },
      {
        "procedure_type": "Refractive index matching",
        "procedure_name": "50% EasyIndex",
        "specimen_id": "662616",
        "start_date": "2023-02-19",
        "end_date": "2023-02-20",
        "experimenter_full_name": "DT",
        "protocol_id": "none",
        "reagents": [
          {
            "name": "EasyIndex",
            "source": "LiveCanvas Technologies",
            "rrid": null,
            "lot_number": "unknown",
            "expiration_date": null
          }
        ],
        "hcr_series": null,
        "immunolabeling": null,
        "notes": "None"
      },
      {
        "procedure_type": "Refractive index matching",
        "procedure_name": "100% EasyIndex",
        "specimen_id": "662616",
        "start_date": "2023-02-20",
        "end_date": "2023-02-21",
        "experimenter_full_name": "DT",
        "protocol_id": "none",
        "reagents": [
          {
            "name": "EasyIndex",
            "source": "LiveCanvas Technologies",
            "rrid": null,
            "lot_number": "unknown",
            "expiration_date": null
          }
        ],
        "hcr_series": null,
        "immunolabeling": null,
        "notes": "None"
      }
    ],
    "notes": null
  },
  "processing": null,
  "rig": null,
  "schema_version": "0.2.7",
  "session": null,
  "subject": {
    "describedBy": "https://raw.githubusercontent.com/AllenNeuralDynamics/aind-data-schema/main/src/aind_data_schema/subject.py",
    "schema_version": "0.4.2",
    "species": {
      "name": "Mus musculus",
      "abbreviation": null,
      "registry": {
        "name": "National Center for Biotechnology Information",
        "abbreviation": "NCBI"
      },
      "registry_identifier": "10090"
    },
    "subject_id": "662616",
    "sex": "Female",
    "date_of_birth": "2022-11-29",
    "genotype": "wt/wt",
    "mgi_allele_ids": null,
    "background_strain": null,
    "source": null,
    "rrid": null,
    "restrictions": null,
    "breeding_group": null,
    "maternal_id": null,
    "maternal_genotype": null,
    "paternal_id": null,
    "paternal_genotype": null,
    "wellness_reports": null,
    "housing": null,
    "notes": null
  }
}]]

Here are some example queries and their filters:
1.
Question: "Retrieve records for subject 740955"
Answer: {'subject.subject_id':'740955'}
2.
Question: "Retrieve records for subjects with genotype 'Sert-Cre/wt' in the project titled:
Discovery-Neuromodulator circuit dynamics during foraging - Subproject 1 Electrophysiological Recordings from NM Neurons During Behavior" 
Answer: {'subject.genotype':'Sert-Cre/wt', "data_description.project_name":"
Discovery-Neuromodulator circuit dynamics during foraging - Subproject 1 Electrophysiological Recordings from NM Neurons During Behavior"}
3. 
Question: "Retrieve records for subject x where qc evaluations for behaviour passed"
Answer: {"subject.subject_id": "792288","quality_control.evaluations": { $elemMatch: { "modality.name": "Behavior", "latest_status": "Pass"} }}
4.
Question: Retrieve records from the openscope project where the session type is OPHYS_9_moving_texture.
Answer: 
 { "data_description.project_name": "OpenScope","session.session_type": "OPHYS_9_moving_texture"}
'''



project_names = get_project_names()

project_session_list = []
for name in project_names:
    sessions= get_session_types(name)
    project_session_list.append({"project_name": name, "sessions":sessions})


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
