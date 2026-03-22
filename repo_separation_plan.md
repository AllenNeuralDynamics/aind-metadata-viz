# Repo Separation Plan: aind-session-utils

## Goal
Extract `aind_session_utils` from `aind-metadata-viz` into its own standalone
package, publish `0.1.0` to PyPI, then pin the dependency here.

---

## Step 1 — Create the new repo (manual, requires GitHub access)

Create a new repo from the AIND library template:

```
cookiecutter https://github.com/AllenNeuralDynamics/aind-library-template
```

When prompted:
- `project_name`: `aind-session-utils`
- `package_name`: `aind_session_utils`
- Anything else: fill in as appropriate

This gives you a repo skeleton with `pyproject.toml`, GitHub Actions workflows
for linting, testing, and PyPI publishing already wired up.

Clone it alongside this repo so the relative path `../aind-session-utils` works:

```
cd /home/doug.ollerenshaw/code
git clone git@github.com:AllenNeuralDynamics/aind-session-utils.git
```

---

## Step 2 — Copy the library source across (can be done by Claude)

Copy the following from `aind-metadata-viz` into `aind-session-utils`:

```
src/aind_session_utils/  →  src/aind_session_utils/
```

The test files in `tests/` here are for the old `aind_metadata_viz.docdb`
module and should NOT be copied. The new repo starts with no tests (acceptable
for 0.1.0; write smoke tests before 1.0).

---

## Step 3 — Write pyproject.toml for the new repo (can be done by Claude)

The template generates a skeleton; fill in the dependencies:

```toml
[project]
name = "aind-session-utils"
version = "0.1.0"
requires-python = ">=3.10"
description = "Query and join AIND session data across DTS, DocDB, and Code Ocean"
authors = [{ name = "Allen Institute for Neural Dynamics" }]
license = { text = "MIT" }
dependencies = [
    "aind-data-access-api[docdb]",
    "codeocean",
    "python-dotenv",
    "pyyaml",
    "pandas",
    "pyarrow",
    "requests",
]
```

---

## Step 4 — Wire up the local path dep in this repo (can be done by Claude)

In `aind-metadata-viz/pyproject.toml`:

1. Add to `dependencies`:
   ```
   "aind-session-utils>=0.1.0",
   ```

2. Add a new section:
   ```toml
   [tool.uv.sources]
   aind-session-utils = { path = "../aind-session-utils", editable = true }
   ```

3. Delete `src/aind_session_utils/` from this repo.

4. Run `uv sync` and verify the viewer still works.

---

## Step 5 — Smoke test (manual)

Serve the viewer locally and load a project to confirm nothing is broken:

```
uv run panel serve src/aind_metadata_viz/session_viewer.py --show
```

---

## Step 6 — Publish 0.1.0 to PyPI (manual, requires PyPI credentials)

In the `aind-session-utils` repo:

```
git tag 0.1.0
git push origin 0.1.0
```

The AIND template's GitHub Actions workflow triggers on tags and pushes to PyPI
automatically (assuming the `PYPI_API_TOKEN` secret is set in the repo settings).

---

## Step 7 — Pin the published version here (can be done by Claude)

Once `0.1.0` is live on PyPI:

1. Remove the `[tool.uv.sources]` block from `pyproject.toml`.
2. Tighten the version pin if desired: `"aind-session-utils==0.1.0"`.
3. Run `uv sync`.
4. Commit and push.

---

## Notes

- **Versioning:** `0.1.0` signals "not yet stable API" (semver `0.x`). Bump to
  `1.0.0` when the public API is considered stable.
- **Future updates:** bump the version in `aind-session-utils`, publish a new
  tag, then update the pin here.
- **Local dev after pinning:** restore the `[tool.uv.sources]` block any time
  you need to make changes to the library and test them before publishing.
