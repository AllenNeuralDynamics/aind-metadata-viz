# aind-metadata-viz

Metadata visualizations

## Usage

Clone the repository and `cd` into the folder

Create a virtual environment and install the package, then launch panel.
```
python -m venv .venv
source .venv/bin/activate (or .venv/bin/Scripts/activate on Windows)
pip install -e .
panel serve ./src/aind_metadata_viz/app.py --show
```