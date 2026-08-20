---
name: zombie-contributions-contract
description: Maintain metadata-viz contributions storage, schemas, permissions, and API behavior consumed by Zombie's contributions app.
---

# Zombie contributions API

The contributions endpoints are `GET /projects`, `GET /get?doi=...`, `POST /post`, `GET /access?doi=...`, and `GET /author-image?orcid=...`. Zombie uses public reads and authenticated writes, so preserve session-cookie credentials and server-side permission checks. New projects require authentication; edits honor `edit_locked`; administrative edits require the server's ORCID/admin check. Do not make the Preact client authoritative for access.

Keep the `ProjectContributions` JSON/YAML shape used by `models.py` and `serializers.py`: credit roles use kebab-case enum values, contribution levels are `lead`, `supporting`, or `equal`, `None` values are omitted, and contributor provenance (`from_asset`), linked assets/sections, DOI, admin, and `edit_locked` survive round trips. The store writes versioned objects under the `aind-scratch-data` bucket and `contributions-app` prefix and selects the latest version by key ordering; preserve that history model rather than overwriting a single object.

Use the existing FastAPI handlers and serializers when adding fields. Test with the repository's fake-S3 and FastAPI `TestClient` fixtures, including public reads, unauthenticated create rejection, locked edits, admin checks, round-trip enum serialization, latest-version selection, and author-image failures.
