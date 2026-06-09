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
from aind_metadata_upgrader.upgrade import Upgrade
from datetime import datetime, timezone
from typing import List, Optional
import asyncio
import copy
import json
import requests
import logging
import traceback

from biodata_query.llm.endpoint import handle_get_query
from biodata_query.query import retrieve_records


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
    
    def get(self):
        """Gather metadata from metadata service like GatherMetadataJob"""
        self.set_header("Content-Type", "application/json")
        
        # Required parameters from query string
        subject_id = self.get_argument('subject_id', None)
        project_name = self.get_argument('project_name', None)

        if not subject_id:
            self.set_status(400)
            self.write({"error": "subject_id is required."})
            return

        if not project_name:
            self.set_status(400)
            self.write({"error": "project_name is required."})
            return

        # Optional parameters with defaults
        metadata_service_url = self.get_argument(
            "metadata_service_url", "http://aind-metadata-service"
        )
        modalities_str = self.get_argument("modalities", "")
        modalities = modalities_str.split(",") if modalities_str else []
        tags_str = self.get_argument("tags", "")
        tags = tags_str.split(",") if tags_str else None
        group = self.get_argument("group", None)
        restrictions = self.get_argument("restrictions", None)
        data_summary = self.get_argument("data_summary", None)
        acquisition_start_time = self.get_argument("acquisition_start_time", None)

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
                acquisition_start_time=acquisition_start_time,
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
        acquisition_start_time: Optional[str],
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
            acquisition_start_time=acquisition_start_time,
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
        acquisition_start_time: Optional[str],
    ) -> dict:
        """Build data description metadata with optional settings"""

        # Use acquisition_start_time if provided, otherwise use current time
        if acquisition_start_time:
            try:
                # Parse the acquisition start time (handle Z suffix)
                iso_time_str = acquisition_start_time.replace("Z", "+00:00")
                creation_time = datetime.fromisoformat(iso_time_str)
            except (ValueError, AttributeError):
                # If parsing fails, fall back to current time
                creation_time = datetime.now(tz=timezone.utc)
        else:
            creation_time = datetime.now(tz=timezone.utc)

        # Get funding information
        funding_source, investigators = self._get_funding(
            project_name, metadata_service_url
        )

        # Convert modalities from abbreviation strings to modality objects
        parsed_modalities = []
        for modality in modalities:
            if isinstance(modality, str):
                try:
                    found_modality = Modality.from_abbreviation(modality.lower())
                    parsed_modalities.append(found_modality)
                except (AttributeError, ValueError):
                    # Keep as string and let validation handle the error
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


class GetQueryHandler(RequestHandler):

    def set_default_headers(self):
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.set_header("Access-Control-Allow-Headers", "Content-Type")

    def options(self):
        self.set_status(204)

    async def get(self):
        event = {
            "queryStringParameters": {
                k: self.get_argument(k)
                for k in self.request.arguments
            }
        }
        response = await asyncio.get_event_loop().run_in_executor(
            None, lambda: handle_get_query(event)
        )
        self.set_status(response["statusCode"])
        self.set_header("Content-Type", "application/json")
        self.write(response["body"])


class RunQueryHandler(RequestHandler):

    def set_default_headers(self):
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.set_header("Access-Control-Allow-Headers", "Content-Type")

    def options(self):
        self.set_status(204)

    async def post(self):
        self.set_header("Content-Type", "application/json")
        try:
            data = json.loads(self.request.body)
        except json.JSONDecodeError:
            self.set_status(400)
            self.write({"error": "Invalid JSON format."})
            return

        if not isinstance(data, dict):
            self.set_status(400)
            self.write({"error": "Request body must be a JSON object."})
            return

        names_only = self.get_argument("names_only", "false").lower() == "true"
        limit_str = self.get_argument("limit", "0")
        try:
            limit = int(limit_str)
        except ValueError:
            self.set_status(400)
            self.write({"error": "limit must be an integer."})
            return

        projection_str = self.get_argument("projection", None)
        projection = None
        if projection_str:
            try:
                projection = json.loads(projection_str)
                if not isinstance(projection, dict):
                    raise ValueError
            except (json.JSONDecodeError, ValueError):
                self.set_status(400)
                self.write({"error": "projection must be a JSON object."})
                return

        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None, lambda: retrieve_records(data, names_only=names_only, limit=limit, projection=projection)
            )
            response_body = {
                "backend": result.backend,
                "elapsed_seconds": result.elapsed_seconds,
                "asset_names": result.asset_names,
            }
            if result.records is not None:
                response_body["records"] = result.records
            self.write(response_body)
        except Exception as e:
            self.set_status(500)
            self.write({"error": "Query execution failed", "details": str(e)})


_UPGRADE_FIELD_CONVERSION_MAP = {
    "session": "acquisition",
    "rig": "instrument",
}

_UPGRADE_CORE_FILES = [
    "data_description",
    "procedures",
    "subject",
    "session",
    "acquisition",
    "rig",
    "instrument",
    "processing",
    "quality_control",
]


def _run_upgrade_on_dict(record: dict) -> dict:
    record = dict(record)
    record.setdefault("_id", record.get("name", "upload"))
    record.setdefault("name", record.get("_id", "upload"))
    record.setdefault("location", "")

    original_record = copy.deepcopy(record)

    results = {
        "overall_success": False,
        "overall_error": None,
        "files_tested": {},
    }

    try:
        upgrader = Upgrade(copy.deepcopy(record))
        upgraded_metadata = upgrader.metadata.model_dump(mode="json")
        results["overall_success"] = True

        for core_file in _UPGRADE_CORE_FILES:
            if core_file in original_record and original_record[core_file]:
                converted_to = _UPGRADE_FIELD_CONVERSION_MAP.get(core_file)
                target_field = converted_to if converted_to else core_file
                results["files_tested"][core_file] = {
                    "success": True,
                    "error": None,
                    "original": original_record[core_file],
                    "upgraded": upgraded_metadata.get(target_field),
                    "converted_to": converted_to,
                }

        return results

    except Exception as e:
        results["overall_error"] = str(e)
        results["overall_traceback"] = traceback.format_exc()

    for core_file in _UPGRADE_CORE_FILES:
        if core_file not in original_record or not original_record[core_file]:
            continue

        converted_to = _UPGRADE_FIELD_CONVERSION_MAP.get(core_file)
        test_dict = {core_file: copy.deepcopy(original_record[core_file])}
        if core_file != "subject" and "subject" in original_record:
            test_dict["subject"] = copy.deepcopy(original_record["subject"])
        test_dict["_id"] = record.get("_id", "upload")
        test_dict["name"] = record.get("name", "upload")
        test_dict["location"] = record.get("location", "")

        try:
            field_upgrader = Upgrade(test_dict, skip_metadata_validation=True)
            field_upgraded = field_upgrader.metadata.model_dump(mode="json")
            target_field = converted_to if converted_to else core_file
            results["files_tested"][core_file] = {
                "success": True,
                "error": None,
                "original": original_record[core_file],
                "upgraded": field_upgraded.get(target_field),
                "converted_to": converted_to,
            }
        except Exception as e:
            results["files_tested"][core_file] = {
                "success": False,
                "error": str(e),
                "original": original_record[core_file],
                "upgraded": None,
                "converted_to": converted_to,
            }

    successful_fields = [
        f for f, r in results["files_tested"].items() if r["success"]
    ]
    results["partial_success"] = len(successful_fields) > 0

    return results


class UpgradeHandler(RequestHandler):

    def set_default_headers(self):
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.set_header("Access-Control-Allow-Headers", "Content-Type")

    def options(self):
        self.set_status(204)

    def post(self):
        self.set_header("Content-Type", "application/json")

        try:
            data = json.loads(self.request.body)
        except json.JSONDecodeError:
            self.set_status(400)
            self.write({"error": "Invalid JSON format."})
            return

        if not isinstance(data, dict):
            self.set_status(400)
            self.write({"error": "Request body must be a JSON object."})
            return

        has_core_fields = any(
            data.get(f) for f in _UPGRADE_CORE_FILES
        )
        if not has_core_fields:
            self.set_status(400)
            self.write({"error": "No recognized metadata fields found in request body."})
            return

        result = _run_upgrade_on_dict(data)
        self.write(result)


from aind_metadata_viz.contributions.handlers import CONTRIBUTION_ROUTES

ROUTES = [
    (r"/gather", GatherHandler),
    (r"/upgrade", UpgradeHandler),
    (r"/validate/metadata", UploadMetadataHandler),
    (r"/validate/files", ValidateFilesHandler),
    (r"/upgrade-query", GetQueryHandler),
    (r"/retrieve-records", RunQueryHandler),
] + INDIVIDUAL_ROUTES + CONTRIBUTION_ROUTES

# Export ROUTES for Panel server to discover
__all__ = ["ROUTES"]
