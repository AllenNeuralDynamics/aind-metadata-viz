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
from aind_data_schema_models.data_name_patterns import DataLevel, Group
from aind_data_schema_models.organizations import Organization
from aind_data_schema_models.modalities import Modality
from datetime import datetime, timezone
from typing import List, Optional
import json
import requests
import logging


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


class GatherHandler(RequestHandler):

    def post(self):
        """Gather metadata from metadata service like GatherMetadataJob"""
        self.set_header("Content-Type", "application/json")

        try:
            data = json.loads(self.request.body)
        except json.JSONDecodeError:
            self.set_status(400)
            self.write({"error": "Invalid JSON format."})
            return

        # Required parameters
        subject_id = data.get("subject_id")
        project_name = data.get("project_name")

        if not subject_id:
            self.set_status(400)
            self.write({"error": "subject_id is required."})
            return

        if not project_name:
            self.set_status(400)
            self.write({"error": "project_name is required."})
            return

        # Optional parameters with defaults
        metadata_service_url = data.get(
            "metadata_service_url", "http://aind-metadata-service"
        )
        modalities = data.get("modalities", [])
        tags = data.get("tags")
        group = data.get("group")
        restrictions = data.get("restrictions")
        data_summary = data.get("data_summary")

        try:
            # Gather metadata from service
            result = self._gather_metadata(
                subject_id=subject_id,
                project_name=project_name,
                metadata_service_url=metadata_service_url,
                modalities=modalities,
                tags=tags,
                group=group,
                restrictions=restrictions,
                data_summary=data_summary,
            )

            self.write(result)

        except Exception as e:
            self.set_status(500)
            self.write(
                {"error": "Failed to gather metadata", "details": str(e)}
            )

    def _gather_metadata(
        self,
        subject_id: str,
        project_name: str,
        metadata_service_url: str,
        modalities: List[str],
        tags: Optional[List[str]],
        group: Optional[str],
        restrictions: Optional[str],
        data_summary: Optional[str],
    ) -> dict:
        """Gather and validate metadata from service"""

        result = {}

        # Get subject metadata (required)
        subject_data = self._get_subject(subject_id, metadata_service_url)
        if not subject_data:
            raise Exception(
                f"Subject metadata not found for subject_id: {subject_id}"
            )

        # Validate subject
        try:
            Subject.model_validate(subject_data)
            result["subject"] = subject_data
        except Exception as e:
            raise Exception(f"Subject validation failed: {str(e)}")

        # Get procedures metadata (required)
        procedures_data = self._get_procedures(
            subject_id, metadata_service_url
        )
        if not procedures_data:
            raise Exception(
                f"Procedures metadata not found for subject_id: {subject_id}"
            )

        # Validate procedures
        try:
            Procedures.model_validate(procedures_data)
            result["procedures"] = procedures_data
        except Exception as e:
            raise Exception(f"Procedures validation failed: {str(e)}")

        # Build data description
        data_description = self._build_data_description(
            project_name=project_name,
            subject_id=subject_id,
            metadata_service_url=metadata_service_url,
            modalities=modalities,
            tags=tags,
            group=group,
            restrictions=restrictions,
            data_summary=data_summary,
        )

        # Validate data description
        try:
            DataDescription.model_validate(data_description)
            result["data_description"] = data_description
        except Exception as e:
            raise Exception(f"DataDescription validation failed: {str(e)}")

        return result

    def _get_subject(
        self, subject_id: str, metadata_service_url: str
    ) -> Optional[dict]:
        """Get subject metadata from service"""
        try:
            response = requests.get(
                f"{metadata_service_url}/api/v2/subject/{subject_id}"
            )
            if response.status_code == 200:
                return response.json().get("data", response.json())
            elif response.status_code == 404:
                logging.warning(f"Subject {subject_id} not found in service")
                return None
            else:
                raise Exception(
                    f"Subject service returned status {response.status_code}"
                )
        except requests.RequestException as e:
            raise Exception(f"Failed to retrieve subject metadata: {str(e)}")

    def _get_procedures(
        self, subject_id: str, metadata_service_url: str
    ) -> Optional[dict]:
        """Get procedures metadata from service"""
        try:
            response = requests.get(
                f"{metadata_service_url}/api/v2/procedures/{subject_id}"
            )
            if response.status_code == 200:
                return response.json().get("data", response.json())
            elif response.status_code == 404:
                logging.warning(
                    f"Procedures for {subject_id} not found in service"
                )
                return None
            else:
                raise Exception(
                    f"Procedures service returned status {response.status_code}"
                )
        except requests.RequestException as e:
            raise Exception(
                f"Failed to retrieve procedures metadata: {str(e)}"
            )

    def _get_funding(
        self, project_name: str, metadata_service_url: str
    ) -> tuple[list, list]:
        """Get funding and investigators metadata from the V2 endpoint"""
        try:
            funding_url = (
                f"{metadata_service_url}/api/v2/funding/{project_name}"
            )
            response = requests.get(funding_url)
            if response.status_code == 200:
                funding_info = response.json()
            else:
                logging.warning(
                    f"Unable to retrieve funding info: {response.status_code}"
                )
                return [], []
        except Exception as e:
            logging.warning(f"Error retrieving funding info: {e}")
            return [], []

        investigators = []
        parsed_funding_info = []

        for f in funding_info:
            project_investigators = f.get("investigators", [])
            investigators.extend(project_investigators)

            funding_info_without_investigators = {
                k: v for k, v in f.items() if k != "investigators"
            }
            parsed_funding_info.append(funding_info_without_investigators)

        # Deduplicate investigators by name and sort
        seen_names = set()
        unique_investigators = []
        for investigator in investigators:
            name = investigator.get("name", "")
            if name and name not in seen_names:
                seen_names.add(name)
                unique_investigators.append(investigator)

        unique_investigators.sort(key=lambda x: x.get("name", ""))
        investigators_list = unique_investigators

        return parsed_funding_info, investigators_list

    def _build_data_description(
        self,
        project_name: str,
        subject_id: str,
        metadata_service_url: str,
        modalities: List[str],
        tags: Optional[List[str]],
        group: Optional[str],
        restrictions: Optional[str],
        data_summary: Optional[str],
    ) -> dict:
        """Build data description metadata with optional settings"""

        creation_time = datetime.now(tz=timezone.utc)

        # Get funding information
        funding_source, investigators = self._get_funding(
            project_name, metadata_service_url
        )

        # Convert modalities to proper enum values if needed
        parsed_modalities = []
        for modality in modalities:
            if isinstance(modality, str):
                # Try to get modality by abbreviation first
                try:
                    found_modality = Modality.from_abbreviation(
                        modality.lower()
                    )
                    parsed_modalities.append(found_modality)
                except (AttributeError, ValueError):
                    # Try by direct attribute access
                    try:
                        found_modality = getattr(Modality, modality.upper())
                        parsed_modalities.append(found_modality)
                    except AttributeError:
                        # Keep as string and let validation handle it
                        parsed_modalities.append(modality)
            else:
                parsed_modalities.append(modality)

        # Convert group to enum if provided
        parsed_group = None
        if group:
            try:
                # Try to find the group in the Group enum by name or value
                for group_option in Group:
                    if (
                        group_option.name.upper() == group.upper()
                        or group_option.value.upper() == group.upper()
                    ):
                        parsed_group = group_option
                        break
                if parsed_group is None:
                    # If not found, try by value directly
                    parsed_group = Group(group.lower())
            except (AttributeError, ValueError):
                # If all fails, leave as None and let validation report the error
                parsed_group = None

        # Create new data description
        new_data_description = DataDescription(
            creation_time=creation_time,
            institution=Organization.AIND,
            project_name=project_name,
            modalities=parsed_modalities,
            funding_source=funding_source,
            investigators=investigators,
            data_level=DataLevel.RAW,
            subject_id=subject_id,
            tags=tags,
            group=parsed_group,
            restrictions=restrictions,
            data_summary=data_summary,
        )

        # Over-write creation_time now that the .name field has been populated
        new_data_description.creation_time = datetime.now(tz=timezone.utc)

        return json.loads(new_data_description.model_dump_json())


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


class ValidateFilesHandler(RequestHandler):

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
            # Modify the data to add required fields
            # Set location to blank string
            data["location"] = ""
            data["object_type"] = "Metadata"

            # Fill name from data_description.name if available
            if "data_description" in data and isinstance(
                data["data_description"], dict
            ):
                if "name" in data["data_description"]:
                    data["name"] = data["data_description"]["name"]
                else:
                    self.set_status(400)
                    self.write(
                        {"error": "data_description.name field is required."}
                    )
                    return
            else:
                self.set_status(400)
                self.write({"error": "data_description field is required."})
                return

            # Validate the modified data as Metadata
            Metadata.model_validate(data)
            self.write(
                {
                    "status": "valid",
                    "message": "Files metadata validation passed",
                }
            )
        except Exception as e:
            # Validation failed - return the error details
            self.set_status(400)
            self.write(
                {
                    "status": "invalid",
                    "error": "Files metadata validation failed",
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
                    self.write(
                        {"error": f"No {type_name.lower()} data provided."}
                    )
                    return

                schema_class.model_validate(data)
                self.write(
                    {
                        "status": "valid",
                        "message": f"{type_name} validation passed",
                    }
                )
            except json.JSONDecodeError:
                self.set_status(400)
                self.write({"error": "Invalid JSON format."})
            except Exception as e:
                self.set_status(400)
                self.write(
                    {
                        "status": "invalid",
                        "error": f"{type_name} validation failed",
                        "details": str(e),
                    }
                )

    return IndividualHandler


# Create individual handlers for each schema type
INDIVIDUAL_ROUTES = [
    (
        f"/validate/{name.lower().replace(' ', '_')}",
        create_individual_handler(cls, name),
    )
    for name, cls in CLASS_MAPPING.items()
]

ROUTES = [
    (r"/gather", GatherHandler),
    (r"/validate/metadata", UploadMetadataHandler),
    (r"/validate/files", ValidateFilesHandler),
] + INDIVIDUAL_ROUTES

# Export ROUTES for Panel server to discover
__all__ = ["ROUTES"]
