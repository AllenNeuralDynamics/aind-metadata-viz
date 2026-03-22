"""Project config loader for aind-session-utils.

YAML config files live in project_configs/ next to this file.  Each file
defines one project that can be selected in the session viewer.

YAML structure
--------------
name: str                          # dropdown label in the viewer
query:
  docdb_project_names: list[str]   # DocDB project_name values to query
  docdb_versions: list[str]        # ["v1"], ["v2"], or ["v1", "v2"]
  dts_job_types:                   # dict of job_type → {expected_pipelines: list}
    <job_type_name>:
      expected_pipelines: list[str]  # modalities whose derived columns are expected
  use_manifests: bool              # optional; enable rig-side manifest detection
pipelines:                         # list of derived asset columns to render
  - label: str
    modalities: list[str]          # lowercase abbreviations (behavior, fib, fiber, ...)
    co_pipeline_capsule_id: str    # optional Code Ocean capsule UUID
    co_log_col: str                # optional column name override for CO log
    co_asset_col: str              # optional column name override for CO asset link
"""

from pathlib import Path

import yaml

_BUNDLED_CONFIG_DIR = Path(__file__).parent / "project_configs"


def _load_yaml_configs(config_dir: Path) -> list[dict]:
    """Load all *.yml files from a directory as parsed dicts."""
    configs = []
    for path in sorted(config_dir.glob("*.yml")):
        with open(path) as fh:
            cfg = yaml.safe_load(fh)
        if cfg and isinstance(cfg, dict) and "name" in cfg:
            configs.append(cfg)
    return configs


def list_project_configs(
    user_config_dir: str | Path | None = None,
) -> list[dict]:
    """Return all available project configs (raw YAML dicts).

    Loads bundled configs first, then user configs.  A user config with the
    same ``name`` as a bundled config takes precedence (override).

    Args:
        user_config_dir: Optional path to a directory of user YAML files.
    """
    by_name: dict[str, dict] = {}
    for cfg in _load_yaml_configs(_BUNDLED_CONFIG_DIR):
        by_name[cfg["name"]] = cfg
    if user_config_dir:
        for cfg in _load_yaml_configs(Path(user_config_dir)):
            by_name[cfg["name"]] = cfg
    return list(by_name.values())


def load_project_config(
    project_name: str,
    user_config_dir: str | Path | None = None,
) -> dict | None:
    """Load a single project config by its display name.

    Returns the parsed YAML dict, or None if not found.
    """
    for cfg in list_project_configs(user_config_dir):
        if cfg["name"] == project_name:
            return cfg
    return None


def to_viewer_config(cfg: dict) -> dict:
    """Convert a raw YAML project config to the format used by session_viewer.py.

    The viewer's internal format uses:
      - ``job_types``: dict[str, dict] with set-valued ``expected_pipelines``
      - ``derived_columns``: list[dict] with set-valued ``modalities``
      - ``docdb_project_names``, ``docdb_versions``, ``use_manifests``

    This function maps the YAML representation to that shape so that
    session_viewer.py requires minimal changes.
    """
    query = cfg.get("query", {})
    pipelines = cfg.get("pipelines", [])

    # dts_job_types in YAML: {job_type: {expected_pipelines: [...]}}
    dts_job_types = query.get("dts_job_types", {})
    job_types: dict[str, dict] = {
        jt: {"expected_pipelines": set(info.get("expected_pipelines", []))}
        for jt, info in (dts_job_types.items() if isinstance(dts_job_types, dict) else {})
    }

    # pipelines in YAML → derived_columns with set-valued modalities
    derived_columns = []
    for p in pipelines:
        col = dict(p)
        col["modalities"] = set(p.get("modalities", []))
        derived_columns.append(col)

    result: dict = {
        "job_types": job_types,
        "docdb_project_names": list(query.get("docdb_project_names") or []),
        "docdb_versions": list(query.get("docdb_versions") or ["v2"]),
        "derived_columns": derived_columns,
    }
    if query.get("use_manifests"):
        result["use_manifests"] = True
    return result
