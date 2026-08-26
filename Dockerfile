FROM python:3.11-slim

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
RUN mkdir -p /tmp/vgraph-jobs /tmp/vgraph-venvs /tmp/vgraph-agent && \
    chown vgraph:vgraph /tmp/vgraph-jobs /tmp/vgraph-venvs /tmp/vgraph-agent
# The verification-graph authoring agent (oh-my-pi). It runs sandboxed, reaches
# Bedrock through the same bedrock-access profile configured below, and can
# only write into its own job directory's outbox.
RUN curl -fsSL https://omp.sh/install | sh || \
    echo "omp not installed; agent jobs will report a missing binary"
RUN pip install . --no-cache-dir
RUN mkdir /root/.aws && \
    cat <<EOF > /root/.aws/config
[profile bedrock-access]
role_arn = arn:aws:iam::024848463001:role/bedrock-access-CO
credential_source = EcsContainer
EOF
# The verification-graph agent runs sandboxed as `vgraph`, which cannot read
# anything under /root, so it gets a readable copy of the same profile. This
# names a role to assume, not a credential, so it is not a secret.
RUN mkdir -p /etc/vgraph && \
    cp /root/.aws/config /etc/vgraph/aws-config && \
    chmod 0644 /etc/vgraph/aws-config
ENV VGRAPH_AGENT_AWS_CONFIG="/etc/vgraph/aws-config"

EXPOSE 8000
ENTRYPOINT ["uvicorn", "aind_metadata_viz.main:app", "--host", "0.0.0.0", "--port", "8000", "--forwarded-allow-ips", "*"]
