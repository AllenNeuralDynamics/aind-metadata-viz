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
