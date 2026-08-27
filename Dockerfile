FROM python:3.12-slim

WORKDIR /app

ENV BIODATA_CACHE_BACKEND="s3"
ENV BIODATA_QUERY_LLM_URL="https://metadata-portal.allenneuraldynamics.org/upgrade-query"
ENV BEDROCK_ROLE_ARN="arn:aws:iam::024848463001:role/bedrock-access-CO"

ADD src ./src
ADD pyproject.toml .
ADD setup.py .

RUN apt-get update
RUN apt-get install -y git
RUN apt-get install -y postgresql
# Verification-graph runner: builds a pinned virtualenv per node code sidecar
# and runs it as an unprivileged user with resource limits (see
# verification/sandbox.py). `coreutils` supplies timeout/nice.
RUN apt-get install -y python3-venv coreutils curl
RUN useradd --system --create-home --shell /usr/sbin/nologin vgraph
RUN mkdir -p /tmp/vgraph-jobs /tmp/vgraph-venvs && \
    chown vgraph:vgraph /tmp/vgraph-jobs /tmp/vgraph-venvs
RUN pip install . --no-cache-dir
RUN mkdir /root/.aws && \
    cat <<EOF > /root/.aws/config
[profile bedrock-access]
role_arn = arn:aws:iam::024848463001:role/bedrock-access-CO
credential_source = EcsContainer
EOF

EXPOSE 8000
ENTRYPOINT ["uvicorn", "aind_metadata_viz.main:app", "--host", "0.0.0.0", "--port", "8000", "--forwarded-allow-ips", "*"]
