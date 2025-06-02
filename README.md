# AIND Metadata Viz

[metadata visualizations](http://10.128.141.92:5007/app)

## Usage

Clone the repository and `cd` into the folder

Create a virtual environment and install the package, then launch panel.
```
python -m venv .venv
source .venv/bin/activate (or .venv/bin/Scripts/activate on Windows)
pip install -e .
panel serve ./src/aind_metadata_viz/app.py --show --autoreload
```

To launch the `query` and `view` apps replace the `app.py` with the appropriate launcher.

## CI/CD
There is a `Dockerfile` which includes the entrypoint to launch the app.

### Local dev
1. Build the Docker image locally and run a Docker container:
```sh
docker build -t aind-metadata-viz .
docker run -e ALLOW_WEBSOCKET_ORIGIN=localhost:8000 -p 8000:8000 aind-metadata-viz
```
2. Navigate to 'localhost:8000` to view the app.

### AWS
1. On pushes to the `dev` or `main` branch, a GitHub Action will run to publish a Docker image to `ghcr.io/allenneuraldynamics/aind-metadata-viz:dev` or `ghcr.io/allenneuraldynamics/aind-metadata-viz:latest`.
2. The image can be used by a ECS Service in AWS to run a task container. Application Load Balancer can be used to serve the container from ECS. Please note that the task must be configured with the correct env variables (e.g. `API_GATEWAY_HOST`, `ALLOW_WEBSOCKET_ORIGIN`).
