FROM python:3.11-slim

WORKDIR /app

ADD src ./src
ADD pyproject.toml .
ADD setup.py .

RUN apt-get update
RUN apt install postgresql
RUN pip install . --no-cache-dir

EXPOSE 8000
ENTRYPOINT ["sh", "-c", "panel serve /app/src/aind_metadata_viz/app.py --static-dirs images=src/aind_metadata_viz/images --address 0.0.0.0 --port 8000 --allow-websocket-origin ${ALLOW_WEBSOCKET_ORIGIN} --keep-alive 10000"]