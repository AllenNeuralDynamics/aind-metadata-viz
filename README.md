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
