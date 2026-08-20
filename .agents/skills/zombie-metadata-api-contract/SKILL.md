---
name: zombie-metadata-api-contract
description: Maintain the metadata-viz API endpoints used by Zombie search, query upgrades, redirects, and metadata upgrades.
---

# Zombie metadata API contract

Zombie search POSTs to `/retrieve-records` (through `/metadata-viz` in production) with either a Mongo-style filter dictionary or an aggregation pipeline. Preserve `names_only`, `limit`, and `projection`; the response must retain `{backend, elapsed_seconds, asset_names}` and include `records` when names-only is false. Do not change the returned asset-name field without updating `web/src/assets/`.

Zombie's natural-language search uses GET `/upgrade-query?message=...&query=...`; preserve query-string forwarding, status codes, and the LLM handler's response body. The `/upgrade` endpoint accepts a body or `asset_name`, returns overall success plus per-file results, and converts legacy metadata fields `session` → `acquisition` and `rig` → `instrument` as the current upgrade implementation does.

The redirect endpoints are compatibility behavior, not a new SPA route. Inspect their targets before changing them: the current source redirects `/view` to Zombie's `/record`, `/upgrade` to `/upgrade`, and legacy `/query`/`/fiber_viewer` targets may not match current Zombie routes (`/search` and platform pages). Keep redirect changes coordinated with `web/build/routes.js` and nginx.

Authentication and CORS are deployment-sensitive. Explicit credentialed origins are required for session-cookie requests; a wildcard CORS origin is not a substitute. Preserve the existing FastAPI validation and error responses. Test with FastAPI `TestClient` and mocked LLM/DocDB/S3 dependencies; cover names-only retrieval, pipelines, limits, field conversion, redirects, and credentialed origins.
