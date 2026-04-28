"""Serialization helpers: convert ProjectContributions to/from JSON and YAML."""

from typing import Union

import yaml

from .models import (
    Author,
    AuthorContribution,
    ContributionLevel,
    CreditRole,
    ProjectContributions,
    RoleContribution,
)

from aind_data_schema_models.registries import Registry


_ROLE_DISPLAY = {
    CreditRole.CONCEPTUALIZATION: "Conceptualization",
    CreditRole.DATA_CURATION: "Data Curation",
    CreditRole.FORMAL_ANALYSIS: "Formal Analysis",
    CreditRole.FUNDING_ACQUISITION: "Funding Acquisition",
    CreditRole.INVESTIGATION: "Investigation",
    CreditRole.METHODOLOGY: "Methodology",
    CreditRole.PROJECT_ADMINISTRATION: "Project Administration",
    CreditRole.RESOURCES: "Resources",
    CreditRole.SOFTWARE: "Software",
    CreditRole.SUPERVISION: "Supervision",
    CreditRole.VALIDATION: "Validation",
    CreditRole.VISUALIZATION: "Visualization",
    CreditRole.WRITING_ORIGINAL_DRAFT: "Writing \u2013 original draft",
    CreditRole.WRITING_REVIEW_EDITING: "Writing \u2013 review & editing",
}

_LEVEL_ORDER = {
    ContributionLevel.LEAD: 2,
    ContributionLevel.EQUAL: 1,
    ContributionLevel.SUPPORTING: 0,
}


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
    """Serialise to YAML matching the authors-real.yml plugin format.

    Standard fields (roles, affiliations) plus plugin-specific blocks
    (credit_levels, section_contributions, timeline) are written at the
    same level under each contributor entry, mirroring the target format
    where the standard contributor schema is extended by the plugin.
    """
    # Build a deduplicated affiliation id map: name -> slug id
    _seen_affiliations: dict = {}
    for c in contributions.contributors:
        for name in c.author.affiliation:
            if name not in _seen_affiliations:
                slug = name.lower().replace(" ", "-").replace(",", "").replace(".", "")
                _seen_affiliations[name] = slug

    contributor_list = []
    for c in contributions.contributors:
        entry = {}
        entry["name"] = c.author.name
        if c.author.registry_identifier:
            entry["orcid"] = c.author.registry_identifier
        if c.author.email:
            entry["email"] = c.author.email
        if c.author.affiliation:
            entry["affiliations"] = [{"id": _seen_affiliations[a]} for a in c.author.affiliation]

        entry["roles"] = [_ROLE_DISPLAY.get(r.role, r.role.value) for r in c.credit_levels]

        entry["credit_levels"] = [
            {"role": _ROLE_DISPLAY.get(r.role, r.role.value), "level": r.level.value}
            for r in c.credit_levels
        ]

        # Build section_contributions: one entry per unique section, ordered
        # by project sections list.  Effort is the highest level of any role
        # that references the section; descriptions are concatenated.
        section_map: dict = {}
        for r in c.credit_levels:
            if not r.linked_sections:
                continue
            for section in r.linked_sections:
                if section not in section_map:
                    section_map[section] = {"effort": r.level, "descriptions": []}
                else:
                    if _LEVEL_ORDER[r.level] > _LEVEL_ORDER[section_map[section]["effort"]]:
                        section_map[section]["effort"] = r.level
                if r.description:
                    section_map[section]["descriptions"].append(r.description)

        if section_map:
            ordered = list(dict.fromkeys(
                ([s for s in contributions.sections if s in section_map])
                + [s for s in section_map if s not in contributions.sections]
            ))
            section_contributions = []
            for s in ordered:
                v = section_map[s]
                sc = {"section": s, "effort": v["effort"].value}
                if v["descriptions"]:
                    sc["description"] = "; ".join(dict.fromkeys(v["descriptions"]))
                section_contributions.append(sc)
            entry["section_contributions"] = section_contributions

        # Build timeline from start_date fields
        start_dates = [r.start_date for r in c.credit_levels if r.start_date]
        if start_dates:
            entry["timeline"] = {"joined": min(start_dates).isoformat()}

        contributor_list.append(entry)

    doc = {
        "version": 1,
        "project": {
            "name": contributions.project_name,
            "contributors": contributor_list,
        },
    }
    if contributions.sections:
        doc["project"]["sections"] = contributions.sections
    if _seen_affiliations:
        doc["project"]["affiliations"] = [
            {"id": slug, "name": name} for name, slug in _seen_affiliations.items()
        ]
    return yaml.dump(doc, allow_unicode=True, sort_keys=False)


def from_yaml(data: str) -> ProjectContributions:
    """Parse a YAML string (authors-real.yml style) into :class:`ProjectContributions`.

    Reads ``project.name`` as ``project_name``.  Per-contributor
    ``credit_levels`` entries supply role and level.  ``affiliations``
    (list of strings) and ``affiliation`` are both accepted.
    """
    doc = yaml.safe_load(data)
    project = doc.get("project", {})
    project_name = project.get("name", "")
    raw_contributors = project.get("contributors", [])
    sections = project.get("sections", [])

    # Build id -> name lookup from top-level affiliations block
    affiliation_lookup: dict = {}
    for aff in project.get("affiliations", []):
        if isinstance(aff, dict) and "id" in aff:
            affiliation_lookup[aff["id"]] = aff.get("name", aff["id"])

    contributors = []
    for raw in raw_contributors:
        raw_affiliations = raw.get("affiliations") or raw.get("affiliation") or []
        resolved = []
        for a in raw_affiliations:
            if isinstance(a, str):
                resolved.append(affiliation_lookup.get(a, a))
            elif isinstance(a, dict):
                aff_id = a.get("id", "")
                resolved.append(affiliation_lookup.get(aff_id, a.get("name", aff_id)))
        author_kwargs = {
            "name": raw["name"],
            "affiliation": resolved,
            "registry_identifier": raw.get("orcid"),
            "email": raw.get("email"),
            "registry": Registry.ORCID,
        }
        author = Author(**author_kwargs)

        credit_levels = []
        for rc in raw.get("credit_levels", []):
            raw_role = rc.get("role", "")
            raw_level = rc.get("level", "")
            _display_to_enum = {v: k for k, v in _ROLE_DISPLAY.items()}
            try:
                role = _display_to_enum.get(raw_role) or CreditRole(raw_role)
                level = ContributionLevel(raw_level)
                credit_levels.append(RoleContribution(role=role, level=level))
            except ValueError:
                continue

        contributors.append(AuthorContribution(author=author, credit_levels=credit_levels))

    return ProjectContributions(
        project_name=project_name,
        contributors=contributors,
        sections=sections,
    )


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
