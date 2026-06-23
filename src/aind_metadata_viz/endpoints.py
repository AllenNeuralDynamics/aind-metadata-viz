from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from aind_data_schema.core.subject import Subject
from aind_data_schema.core.data_description import DataDescription
from aind_data_schema.core.procedures import Procedures
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

from aind_data_access_api.document_db import MetadataDbClient
from biodata_query.llm.endpoint import handle_get_query
from biodata_query.query import retrieve_aggregation, retrieve_records

_DOCDB_HOST = "api.allenneuraldynamics.org"


router = APIRouter()


@router.get("/health")
async def health_check():
    return JSONResponse(status_code=200, content={"status": "healthy"})


@router.get("/view")
async def redirect_view(name: str = ""):
    return RedirectResponse(url=f"https://data.allenneuraldynamics.org/record?name={name}", status_code=301)


@router.get("/fiber_viewer")
async def redirect_fiber_viewer(subject_id: str = ""):
    return RedirectResponse(url=f"https://data.allenneuraldynamics.org/subject?subject_id={subject_id}", status_code=301)


@router.get("/query")
async def redirect_query():
    return RedirectResponse(url="https://data.allenneuraldynamics.org/assets", status_code=301)


@router.get("/upgrade")
async def redirect_upgrade():
    return RedirectResponse(url="https://data.allenneuraldynamics.org/upgrade", status_code=301)


def _get_subject(subject_id: str, metadata_service_url: str) -> Optional[dict]:
    try:
        response = requests.get(f"{metadata_service_url}/api/v2/subject/{subject_id}")
        if response.status_code == 200:
            return response.json().get("data", response.json())
        elif response.status_code == 404:
            logging.warning(f"Subject {subject_id} not found in service")
            return None
        else:
            raise Exception(f"Subject service returned status {response.status_code}")
    except requests.RequestException as e:
        raise Exception(f"Failed to retrieve subject metadata: {str(e)}")


def _get_procedures(subject_id: str, metadata_service_url: str) -> Optional[dict]:
    try:
        response = requests.get(f"{metadata_service_url}/api/v2/procedures/{subject_id}")
        if response.status_code == 200:
            return response.json().get("data", response.json())
        elif response.status_code == 404:
            logging.warning(f"Procedures for {subject_id} not found in service")
            return None
        else:
            raise Exception(f"Procedures service returned status {response.status_code}")
    except requests.RequestException as e:
        raise Exception(f"Failed to retrieve procedures metadata: {str(e)}")


def _get_funding(project_name: str, metadata_service_url: str) -> tuple:
    try:
        funding_url = f"{metadata_service_url}/api/v2/funding/{project_name}"
        response = requests.get(funding_url)
        if response.status_code == 200:
            funding_info = response.json()
        else:
            logging.warning(f"Unable to retrieve funding info: {response.status_code}")
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

    seen_names = set()
    unique_investigators = []
    for investigator in investigators:
        name = investigator.get("name", "")
        if name and name not in seen_names:
            seen_names.add(name)
            unique_investigators.append(investigator)

    unique_investigators.sort(key=lambda x: x.get("name", ""))
    return parsed_funding_info, unique_investigators


def _build_data_description(
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
    if acquisition_start_time:
        try:
            iso_time_str = acquisition_start_time.replace("Z", "+00:00")
            creation_time = datetime.fromisoformat(iso_time_str)
        except (ValueError, AttributeError):
            creation_time = datetime.now(tz=timezone.utc)
    else:
        creation_time = datetime.now(tz=timezone.utc)

    funding_source, investigators = _get_funding(project_name, metadata_service_url)

    parsed_modalities = []
    for modality in modalities:
        if isinstance(modality, str):
            try:
                found_modality = Modality.from_abbreviation(modality.lower())
                parsed_modalities.append(found_modality)
            except (AttributeError, ValueError):
                parsed_modalities.append(modality)
        else:
            parsed_modalities.append(modality)

    parsed_group = None
    if group:
        try:
            for group_option in Group:
                if (
                    group_option.name.upper() == group.upper()
                    or group_option.value.upper() == group.upper()
                ):
                    parsed_group = group_option
                    break
            if parsed_group is None:
                parsed_group = Group(group.lower())
        except (AttributeError, ValueError):
            parsed_group = None

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

    new_data_description.creation_time = datetime.now(tz=timezone.utc)
    return json.loads(new_data_description.model_dump_json())


def _gather_metadata(
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
    result = {}

    subject_data = _get_subject(subject_id, metadata_service_url)
    if not subject_data:
        raise Exception(f"Subject metadata not found for subject_id: {subject_id}")

    try:
        Subject.model_validate(subject_data)
        result["subject"] = subject_data
    except Exception as e:
        raise Exception(f"Subject validation failed: {str(e)}")

    procedures_data = _get_procedures(subject_id, metadata_service_url)
    if not procedures_data:
        raise Exception(f"Procedures metadata not found for subject_id: {subject_id}")

    try:
        Procedures.model_validate(procedures_data)
        result["procedures"] = procedures_data
    except Exception as e:
        raise Exception(f"Procedures validation failed: {str(e)}")

    data_description = _build_data_description(
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

    try:
        DataDescription.model_validate(data_description)
        result["data_description"] = data_description
    except Exception as e:
        raise Exception(f"DataDescription validation failed: {str(e)}")

    return result


@router.post("/gather")
async def gather(request: Request):
    try:
        data = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Invalid JSON format."})

    subject_id = data.get("subject_id")
    project_name = data.get("project_name")

    if not subject_id:
        return JSONResponse(status_code=400, content={"error": "subject_id is required."})

    if not project_name:
        return JSONResponse(status_code=400, content={"error": "project_name is required."})

    metadata_service_url = data.get("metadata_service_url", "http://aind-metadata-service")
    modalities_raw = data.get("modalities", [])
    modalities = modalities_raw if isinstance(modalities_raw, list) else modalities_raw.split(",")
    tags_raw = data.get("tags", None)
    tags = tags_raw if isinstance(tags_raw, list) else (tags_raw.split(",") if tags_raw else None)
    group = data.get("group", None)
    restrictions = data.get("restrictions", None)
    data_summary = data.get("data_summary", None)
    acquisition_start_time = data.get("acquisition_start_time", None)

    try:
        result = _gather_metadata(
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
        return JSONResponse(content=result)
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": "Failed to gather metadata", "details": str(e)},
        )


@router.get("/upgrade-query")
async def upgrade_query(request: Request):
    event = {"queryStringParameters": dict(request.query_params)}
    response = await asyncio.get_event_loop().run_in_executor(
        None, lambda: handle_get_query(event)
    )
    return Response(
        content=response["body"],
        status_code=response["statusCode"],
        media_type="application/json",
    )


@router.post("/retrieve-records")
async def retrieve_records_endpoint(request: Request):
    try:
        data = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Invalid JSON format."})

    # Aggregation path: body is a list (MongoDB aggregation pipeline)
    if isinstance(data, list):
        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: retrieve_aggregation(data),
            )
            response_body = {
                "backend": result.backend,
                "elapsed_seconds": result.elapsed_seconds,
                "asset_names": result.asset_names,
            }
            if result.records is not None:
                response_body["records"] = result.records
            return JSONResponse(content=response_body)
        except Exception as e:
            return JSONResponse(
                status_code=500,
                content={"error": "Aggregation execution failed", "details": str(e)},
            )

    if not isinstance(data, dict):
        return JSONResponse(status_code=400, content={"error": "Request body must be a JSON object or a list (aggregation pipeline)."})

    names_only = request.query_params.get("names_only", "false").lower() == "true"
    limit_str = request.query_params.get("limit", "0")
    try:
        limit = int(limit_str)
    except ValueError:
        return JSONResponse(status_code=400, content={"error": "limit must be an integer."})

    projection_str = request.query_params.get("projection", None)
    projection = None
    if projection_str:
        try:
            projection = json.loads(projection_str)
            if not isinstance(projection, dict):
                raise ValueError
        except (json.JSONDecodeError, ValueError):
            return JSONResponse(status_code=400, content={"error": "projection must be a JSON object."})

    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: retrieve_records(data, names_only=names_only, limit=limit, projection=projection),
        )
        response_body = {
            "backend": result.backend,
            "elapsed_seconds": result.elapsed_seconds,
            "asset_names": result.asset_names,
        }
        if result.records is not None:
            response_body["records"] = result.records
        return JSONResponse(content=response_body)
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": "Query execution failed", "details": str(e)},
        )


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

    successful_fields = [f for f, r in results["files_tested"].items() if r["success"]]
    results["partial_success"] = len(successful_fields) > 0

    return results


@router.post("/upgrade")
async def upgrade_endpoint(request: Request, asset_name: Optional[str] = None):
    if asset_name:
        try:
            def _fetch_v1_record():
                client = MetadataDbClient(host=_DOCDB_HOST, version="v1")
                records = client.retrieve_docdb_records(filter_query={"name": asset_name})
                return records

            records = await asyncio.get_event_loop().run_in_executor(None, _fetch_v1_record)
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": f"Failed to fetch record: {str(e)}"})

        if not records:
            return JSONResponse(status_code=404, content={"error": f"Asset '{asset_name}' not found."})

        data = records[0]
    else:
        try:
            data = await request.json()
        except Exception:
            return JSONResponse(status_code=400, content={"error": "Invalid JSON format."})

        if not isinstance(data, dict):
            return JSONResponse(status_code=400, content={"error": "Request body must be a JSON object."})

        has_core_fields = any(data.get(f) for f in _UPGRADE_CORE_FILES)
        if not has_core_fields:
            return JSONResponse(
                status_code=400,
                content={"error": "No recognized metadata fields found in request body."},
            )

    result = _run_upgrade_on_dict(data)
    return JSONResponse(content=result)
