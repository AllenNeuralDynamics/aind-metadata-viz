FROM python:3.11-slim

WORKDIR /app

# Copy the Panel app code
ADD src ./src
ADD pyproject.toml .
ADD setup.py .

RUN apt-get update
RUN pip install . --no-cache-dir

EXPOSE 8000


ENTRYPOINT ["panel", "serve", "/app/src/aind_metadata_viz/app.py", "--static-dirs", "images=src/aind_metadata_viz/images", "--port", "8000", "--allow-websocket-origin", "0.0.0.0", "--keep-alive", "10000"]