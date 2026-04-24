"""Serialization helpers: convert ProjectContributions to/from JSON and YAML."""

from typing import Union

import yaml

from .models import (
    AuthorContribution,
    ContributionLevel,
    CreditRole,
    ProjectContributions,
    RoleContribution,
)

try:
    from aind_data_schema.core.data_description import Person
    from aind_data_schema_models.registries import Registry
except ImportError:  # pragma: no cover
    Person = None  # type: ignore
    Registry = None  # type: ignore


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------


def to_json(contributions: ProjectContributions) -> str:
    """Return a JSON string of the ProjectContributions model."""
    return contributions.model_dump_json(indent=2)


def from_json(data: str) -> ProjectContributions:
    """Parse a JSON string produced by :func:`to_json`."""
    return ProjectContributions.model_validate_json(data)


# ---------------------------------------------------------------------------
# YAML  (authors-real.yml style)
# ---------------------------------------------------------------------------


def to_yaml(contributions: ProjectContributions) -> str:
    """Serialise to YAML matching the authors-real.yml credit_levels format.

    Example output per contributor::

        - name: Jane Smith
          orcid: 0000-0000-0000-0001
          credit_levels:
            - role: Conceptualization
              level: lead
    """
    contributor_list = []
    for c in contributions.contributors:
        entry = {
            "name": c.person.name,
            "orcid": c.person.registry_identifier,
            "credit_levels": [
                {"role": r.role.value, "level": r.level.value}
                for r in c.credit_levels
            ],
        }
        contributor_list.append(entry)

    doc = {
        "version": 1,
        "project": {
            "name": contributions.project_name,
            "contributors": contributor_list,
        },
    }
    return yaml.dump(doc, allow_unicode=True, sort_keys=False)


def from_yaml(data: str) -> ProjectContributions:
    """Parse a YAML string (authors-real.yml style) into :class:`ProjectContributions`.

    Expects the structure produced by :func:`to_yaml`.  The ``project.name``
    key is used as ``project_name``; fall back to an empty string if absent.
    """
    doc = yaml.safe_load(data)
    project = doc.get("project", {})
    project_name = project.get("name", "")
    raw_contributors = project.get("contributors", [])

    contributors = []
    for raw in raw_contributors:
        person_kwargs = {
            "name": raw["name"],
            "registry_identifier": raw.get("orcid"),
        }
        if Registry is not None:
            person_kwargs["registry"] = Registry.ORCID
        person = Person(**person_kwargs)

        credit_levels = []
        for rc in raw.get("credit_levels", []):
            try:
                role = CreditRole(rc["role"])
                level = ContributionLevel(rc["level"])
                credit_levels.append(RoleContribution(role=role, level=level))
            except ValueError:
                # Skip unrecognised roles / levels rather than crashing
                continue

        contributors.append(AuthorContribution(person=person, credit_levels=credit_levels))

    return ProjectContributions(project_name=project_name, contributors=contributors)


# ---------------------------------------------------------------------------
# Auto-detect format helper
# ---------------------------------------------------------------------------


def load(data: Union[str, dict]) -> ProjectContributions:
    """Load from a JSON string, YAML string, or already-parsed dict."""
    if isinstance(data, dict):
        return ProjectContributions.model_validate(data)
    stripped = data.strip()
    if stripped.startswith("{"):
        return from_json(stripped)
    return from_yaml(stripped)
