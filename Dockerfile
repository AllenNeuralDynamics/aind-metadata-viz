FROM python:3.10-slim

WORKDIR /app

ENV FOREST_TYPE="s3"
ENV BIODATA_QUERY_LLM_URL="https://metadata-portal.allenneuraldynamics.org/get-query"

ADD src ./src
ADD pyproject.toml .
ADD setup.py .

RUN apt-get update
RUN apt-get install -y git
RUN apt-get install -y postgresql
RUN pip install . --no-cache-dir
RUN mkdir /root/.aws && \
    cat <<EOF > /root/.aws/config
[profile bedrock-access]
role_arn = arn:aws:iam::024848463001:role/bedrock-access-CO
credential_source = EcsContainer
EOF

EXPOSE 8000
ENTRYPOINT ["sh", "-c", "panel serve src/aind_metadata_viz/app.py src/aind_metadata_viz/view.py src/aind_metadata_viz/query.py src/aind_metadata_viz/upgrade.py src/aind_metadata_viz/fiber_viewer.py --static-dirs images=src/aind_metadata_viz/images --plugins aind_metadata_viz.endpoints --address 0.0.0.0 --port 8000 --allow-websocket-origin ${ALLOW_WEBSOCKET_ORIGIN} --keep-alive 10000 --index app.py"]
