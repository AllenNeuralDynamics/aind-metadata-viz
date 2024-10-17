# AIND Metadata Viz

[metadata visualizations](http://10.128.141.92:5007/app)

## Usage

Clone the repository and `cd` into the folder

Create a virtual environment and install the package, then launch panel.
```
python -m venv .venv
source .venv/bin/activate (or .venv/bin/Scripts/activate on Windows)
pip install -e .
panel serve ./src/aind_metadata_viz/app.py --show
```

## Release

We directly expose the process/port on the internal AI network. To update and restart:

To update build
```
ssh ibs-davidf-vm2
cd aind-metadata-viz
git pull
```

To restart
```
ps aux | grep panel
kill pid
./start_viz.sh
```

`start_viz.sh` is:
```
#!/bin/bash -x

cd ~/aind-metadata-viz

source .venv/bin/activate
pip install -e .

nohup panel serve ./src/aind_metadata_viz/app.py --allow-websocket-origin=10.128.141.92:5006 > ~/logfile.log 2>&1 &
```

The process (should) auto-restart on reboot. See `crontab -e`

## CI/CD
There is a `Dockerfile` which includes the entrypoint to launch the app.

### Local dev
1. Build the Docker image locally and run a Docker container:
```sh
docker build -t aind-metadata-viz .
docker run -e ALLOW_WEBSOCKET_ORIGIN=localhost:8000 -p 8000:8000 aind-metadata-viz
```
2. Navigate to 'localhost:8000` to view the app.

### Dev
1. On pushes to the `dev` branch, a GitHub Action will run to publish a Docker image to `ghcr.io/allenneuraldynamics/aind-metadata-viz:dev`.