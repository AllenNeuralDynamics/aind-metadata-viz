# AIND Metadata Portal

[metadata visualizations](https://metadata-portal.allenneuraldynamics.org/)

## REST API

The portal exposes a REST API served by FastAPI/uvicorn. Full interactive API documentation —
every endpoint, request/response schemas, and a "try it out" console — is served at `/docs`
(Swagger UI) and `/redoc`:

- https://metadata-portal.allenneuraldynamics.org/docs
- https://metadata-portal.allenneuraldynamics.org/redoc

## Local dev

```sh
uv sync --extra dev
uvicorn aind_metadata_viz.main:app --reload
```

Then visit http://localhost:8000/docs to browse and try the API locally.

## Environment variables

### Contributions endpoint

The contributions endpoints persist project data as JSON objects in the S3 bucket
`aind-scratch-data` (prefix `contributions-app/`) via `boto3`, and gate edits behind ORCID
login. The server must be configured with:

- **AWS credentials** with read/write access to the `aind-scratch-data` bucket. Provide these
  via the standard AWS mechanisms — an attached IAM role (preferred on ECS), or
  `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` (plus `AWS_SESSION_TOKEN` if using temporary
  credentials). Set `AWS_REGION` (or `AWS_DEFAULT_REGION`) to the bucket's region.
- `ORCID_CLIENT_ID`, `ORCID_CLIENT_SECRET` — credentials of the registered ORCID API client
  (register at https://orcid.org Developer Tools with redirect URI
  `{PUBLIC_BASE_URL}/auth/orcid/callback`).
- `SESSION_SECRET` — secret key used to sign the session cookie. **Required in production**
  (defaults to an insecure dev value otherwise).
- `PUBLIC_BASE_URL` — public base URL of this service, used to build the OAuth redirect URI.
- `ADMIN_ORCIDS` — comma-separated ORCID iDs granted admin privileges (admins may edit any
  project).
- `ORCID_ISSUER` — OIDC issuer base URL. Optional, defaults to `https://orcid.org`.

## CI/CD

There is a `Dockerfile` which includes the entrypoint to launch the app.

### Local dev via Docker

```sh
docker build -t aind-metadata-viz .
docker run -p 8000:8000 aind-metadata-viz
```

### AWS

1. On pushes to the `dev` or `main` branch, a GitHub Action will run to publish a Docker image to
   `ghcr.io/allenneuraldynamics/aind-metadata-viz:dev` or
   `ghcr.io/allenneuraldynamics/aind-metadata-viz:latest`.
2. The image can be used by an ECS Service in AWS to run a task container. Application Load
   Balancer can be used to serve the container from ECS. Please note that the task must be
   configured with the correct env variables (e.g. `API_GATEWAY_HOST`, `ALLOW_WEBSOCKET_ORIGIN`).
