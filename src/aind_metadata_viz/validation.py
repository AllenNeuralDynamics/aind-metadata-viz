from tornado.web import RequestHandler
from aind_data_schema.core.metadata import Metadata
from aind_data_schema.core.acquisition import Acquisition
from aind_data_schema.core.subject import Subject
from aind_data_schema.core.data_description import DataDescription
from aind_data_schema.core.instrument import Instrument
from aind_data_schema.core.quality_control import QualityControl
from aind_data_schema.core.processing import Processing
from aind_data_schema.core.procedures import Procedures
from aind_data_schema.core.model import Model
import json


CLASS_MAPPING = {
    "Metadata": Metadata,
    "Acquisition": Acquisition,
    "Subject": Subject,
    "Data description": DataDescription,
    "Instrument": Instrument,
    "Quality control": QualityControl,
    "Processing": Processing,
    "Procedures": Procedures,
    "Model": Model,
}


class UploadMetadataHandler(RequestHandler):

    def post(self):
        self.set_header("Content-Type", "application/json")

        try:
            data = json.loads(self.request.body)
        except json.JSONDecodeError:
            self.set_status(400)
            self.write({"error": "Invalid JSON format."})
            return

        if not data:
            self.set_status(400)
            self.write({"error": "No metadata provided."})
            return

        try:
            if "object_type" in data and data["object_type"] in CLASS_MAPPING:
                CLASS_MAPPING[data["object_type"]].model_validate(data)
                self.write(
                    {
                        "status": "valid",
                        "message": "Metadata validation passed",
                    }
                )
            else:
                self.set_status(400)
                self.write({"error": "Unknown or missing object_type."})
        except Exception as e:
            # Validation failed - return the error details
            self.set_status(400)
            self.write(
                {
                    "status": "invalid",
                    "error": "Metadata validation failed",
                    "details": str(e),
                }
            )


def create_individual_handler(schema_class, type_name):
    """Factory function to create individual validation handlers"""
    class IndividualHandler(RequestHandler):
        def post(self):
            self.set_header("Content-Type", "application/json")
            try:
                data = json.loads(self.request.body)
                if not data:
                    self.set_status(400)
                    self.write({"error": f"No {type_name.lower()} data provided."})
                    return
                
                schema_class.model_validate(data)
                self.write({"status": "valid", "message": f"{type_name} validation passed"})
            except json.JSONDecodeError:
                self.set_status(400)
                self.write({"error": "Invalid JSON format."})
            except Exception as e:
                self.set_status(400)
                self.write({"status": "invalid", "error": f"{type_name} validation failed", "details": str(e)})
    
    return IndividualHandler


# Create individual handlers for each schema type
INDIVIDUAL_ROUTES = [
    (f"/validate/{name.lower().replace(' ', '_')}", create_individual_handler(cls, name))
    for name, cls in CLASS_MAPPING.items()
]

ROUTES = [
    (r"/validate/metadata", UploadMetadataHandler),
] + INDIVIDUAL_ROUTES

# Export ROUTES for Panel server to discover
__all__ = ["ROUTES"]
