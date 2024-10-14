FROM python:3.11-slim

# Copy the Panel app code
WORKDIR /app
COPY . /app

# Install dependencies
RUN pip install -e /app/. --no-cache-dir

# Expose the port that the Panel app will run on
EXPOSE 5006

# Command to run the Panel app
CMD ["panel", "serve", "/app/src/aind_metadata_viz/app.py", "--allow-websocket-origin=*", "--port=5006", "--address=0.0.0.0"]
