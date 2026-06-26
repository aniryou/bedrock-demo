# AgentCore Runtime image for the order-triage agent.
# AgentCore Runtime requires linux/arm64 and a server on port 8080 exposing
# /invocations and /ping (BedrockAgentCoreApp provides both).
FROM --platform=linux/arm64 public.ecr.aws/docker/library/python:3.12-slim

WORKDIR /app

# Install the project + deploy extras (bedrock-agentcore, aws-opentelemetry-distro).
# `skills/` and `ontology/` are fetched from order-triage-knowledge by CI
# (`make skills`) before build, pinned to the same release ref.
COPY pyproject.toml README.md ./
COPY src ./src
COPY skills ./skills
COPY ontology ./ontology
RUN pip install --no-cache-dir ".[deploy]"

ENV SKILLS_DIR=/app/skills \
    ONTOLOGY_DIR=/app/ontology \
    PYTHONUNBUFFERED=1

EXPOSE 8080

# Launch under opentelemetry-instrument so AgentCore Observability captures traces
# automatically (aws-opentelemetry-distro is installed above).
CMD ["opentelemetry-instrument", "python", "-m", "order_triage.runtime"]
