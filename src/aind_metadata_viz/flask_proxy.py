from flask import Flask, send_from_directory, redirect
import subprocess

app = Flask(__name__)

# Start the Panel server
subprocess.Popen(["panel", "serve", "src/aind_metadata_viz/app.py", "--address", "0.0.0.0", "--port", "5006"])


@app.route('/')
def index():
    return redirect("/app")


@app.route('/<path:path>')
def proxy(path):
    return send_from_directory('static', path)


if __name__ == '__main__':
    app.run(host="0.0.0.0", port=8000)