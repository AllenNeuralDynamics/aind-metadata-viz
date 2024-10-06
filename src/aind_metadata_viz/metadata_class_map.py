### class that does xxxx for something with QC

# First level metadata models
from aind_data_schema.core.acquisition import Acquisition
from aind_data_schema.core.data_description import DataDescription
from aind_data_schema.core.instrument import Instrument
from aind_data_schema.core.processing import Processing
from aind_data_schema.core.procedures import Procedures
from aind_data_schema.core.quality_control import QualityControl
from aind_data_schema.core.rig import Rig
from aind_data_schema.core.session import Session
from aind_data_schema.core.subject import Subject

# General Models
from typing import List, Optional, Dict, Union, Set
from datetime import date, datetime

# Acquisition Models
from aind_data_schema.components.devices import (
    Calibration,
    Maintenance,
    Software,
)
from aind_data_schema.components.tile import AcquisitionTile
from aind_data_schema.components.coordinates import ImageAxis
from aind_data_schema.core.acquisition import Immersion, ProcessingSteps

# Data Description Models
from aind_data_schema_models.modalities import Modality
from aind_data_schema_models.organizations import Organization
from aind_data_schema_models.pid_names import PIDName
from aind_data_schema_models.platforms import Platform
from aind_data_schema_models.data_name_patterns import (
    DataLevel,
    Group,
)
from aind_data_schema.core.data_description import RelatedData, Funding

# Instrument Models
from aind_data_schema.components.devices import (
    LIGHT_SOURCES,
    AdditionalImagingDevice,
    DAQDevice,
    Detector,
    Enclosure,
    Filter,
    ImagingInstrumentType,
    Lens,
    MotorizedStage,
    Objective,
    OpticalTable,
    ScanningStage,
)
from aind_data_schema.core.instrument import Com

# Metadata Models
from aind_data_schema.core.metadata import MetadataStatus, ExternalPlatforms

# Procedures Models
from aind_data_schema.core.procedures import (
    Surgery,
    TrainingProtocol,
    WaterRestriction,
    OtherSubjectProcedure,
)

# Processing Models
from aind_data_schema.core.processing import AnalysisProcess, PipelineProcess

# Quality Control Models
from aind_data_schema.core.quality_control import QCStatus, QCEvaluation

# Rig Models
from aind_data_schema.core.rig import (
    MOUSE_PLATFORMS,
    STIMULUS_DEVICES,
    RIG_DAQ_DEVICES,
)
from aind_data_schema.components.coordinates import Axis, Origin
from aind_data_schema.components.devices import (
    LIGHT_SOURCES,
    Calibration,
    CameraAssembly,
    DAQDevice,
    Detector,
    Device,
    DigitalMicromirrorDevice,
    Enclosure,
    EphysAssembly,
    FiberAssembly,
    Filter,
    LaserAssembly,
    Lens,
    Objective,
    Patch,
    PolygonalScanner,
)

# Session Models
from aind_data_schema_models.units import (
    MassUnit,
    VolumeUnit,
)
from aind_data_schema.core.procedures import Anaesthetic
from aind_data_schema.core.session import (
    Stream,
    StimulusEpoch,
    RewardDeliveryConfig,
)
from aind_data_schema.components.coordinates import Affine3dTransform

# Subject Models
from aind_data_schema.core.subject import (
    BackgroundStrain,
    BreedingInfo,
    WellnessReport,
    Housing,
)
from aind_data_schema_models.species import Species

first_layer_field_mapping = {
    "data_description": DataDescription,
    "acquisition": Acquisition,
    "procedures": Procedures,
    "subject": Subject,
    "instrument": Instrument,
    "processing": Processing,
    "rig": Rig,
    "session": Session,
    "quality_control": QualityControl,
}
second_layer_field_mappings = {
    "acquisition": {
        "calibrations": List[Calibration],
        "maintenance": List[Maintenance],
        "tiles": List[AcquisitionTile],
        "axes": List[ImageAxis],
        "chamber_immersion": Immersion,
        "sample_immersion": Optional[Immersion],
        "processing_steps": List[ProcessingSteps],
        "software": Optional[List[Software]],
    },
    "data_description": {
        "data_level": DataLevel,
        "group": Optional[Group],
        "investigators": List[PIDName],
        "modality": List[Modality],
        "related_data": List[RelatedData],
        "platform": Platform.ONE_OF,
        "funding_source": List[Funding],
        "institution": Organization.RESEARCH_INSTITUTIONS,
    },
    "instrument": {
        "instrument_type": ImagingInstrumentType,
        "manufacturer": Organization.ONE_OF,
        "optical_tables": List[OpticalTable],
        "enclosure": Optional[Enclosure],
        "objectives": List[Objective],
        "detectors": List[Detector],
        "light_sources": List[LIGHT_SOURCES],
        "lenses": List[Lens],
        "fluorescence_filters": List[Filter],
        "motorized_stages": List[MotorizedStage],
        "scanning_stages": List[ScanningStage],
        "additional_devices": List[AdditionalImagingDevice],
        "calibration_date": Optional[date],
        "com_ports": List[Com],
        "daqs": List[DAQDevice],
    },
    "metadata": {
        **first_layer_field_mapping,
        "created": datetime,
        "last_modified": datetime,
        "metadata_status": MetadataStatus,
        "external_links": Dict[ExternalPlatforms, List[str]],
    },
    "procedures": {
        "subject_procedures": List[  # This one is really weird, not sure how to go about converting it. All of the procedures schema will be difficult to do this with, since some fields can have a range of 12+ models input into them.
            Union[
                Surgery,
                TrainingProtocol,
                WaterRestriction,
                OtherSubjectProcedure,
            ],
        ],
    },
    "processing": {
        "processing_pipeline": PipelineProcess,
        "analyses": List[AnalysisProcess],
    },
    "quality_control": {
        "overall_status": List[QCStatus],
        "evaluations": List[QCEvaluation],
    },
    "rig": {
        "modification_date": date,
        "mouse_platform": MOUSE_PLATFORMS,
        "stimulus_devices": List[STIMULUS_DEVICES],
        "cameras": List[CameraAssembly],
        "enclosure": Optional[Enclosure],
        "ephys_assemblies": List[EphysAssembly],
        "fiber_assemblies": List[FiberAssembly],
        "stick_microscopes": List[CameraAssembly],
        "laser_assemblies": List[LaserAssembly],
        "patch_cords": List[Patch],
        "light_sources": List[LIGHT_SOURCES],
        "detectors": List[Detector],
        "objectives": List[Objective],
        "filters": List[Filter],
        "lenses": List[Lens],
        "digital_micromirror_devices": List[DigitalMicromirrorDevice],
        "polygonal_scanners": List[PolygonalScanner],
        "additional_devices": List[Device],
        "daqs": List[RIG_DAQ_DEVICES],
        "calibrations": List[Calibration],
        "origin": Optional[Origin],
        "rig_axes": Optional[List[Axis]],
        "modalities": Set[Modality.ONE_OF],
    },
    "session": {
        "calibrations": List[Calibration],
        "maintenance": List[Maintenance],
        "weight_unit": MassUnit,
        "anaesthesia": Optional[Anaesthetic],
        "data_streams": List[Stream],
        "stimulus_epochs": List[StimulusEpoch],
        "headframe_registration": Optional[Affine3dTransform],
        "reward_delivery": Optional[RewardDeliveryConfig],
        "reward_consumed_unit": VolumeUnit,
    },
    "subject": {
        "date_of_birth": date,
        "species": Species.ONE_OF,
        "alleles": List[PIDName],
        "background_strain": Optional[BackgroundStrain],
        "breeding_info": Optional[BreedingInfo],
        "source": Organization.SUBJECT_SOURCES,
        "rrid": Optional[PIDName],
        "wellness_reports": List[WellnessReport],
        "housing": Optional[Housing],
    },
}
