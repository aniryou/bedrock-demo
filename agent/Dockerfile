# AgentCore Runtime image for the order-triage agent.
# AgentCore Runtime requires linux/arm64 and a server on port 8080 exposing
# /invocations and /ping (BedrockAgentCoreApp provides both).
#
# Built with the REPO ROOT as the build context: the agent is a thin consumer of the
# in-tree `lib/` (agent_kit), so both folders are copied and installed.
FROM --platform=linux/arm64 public.ecr.aws/docker/library/python:3.12-slim

WORKDIR /app

# Install agent_kit with the deploy extras (bedrock-agentcore, aws-opentelemetry-distro);
# the agent's runtime deps (strands, boto3, pyyaml) arrive transitively from it.
COPY lib ./lib
RUN pip install --no-cache-dir ./lib[deploy]

# Install the thin agent package. `skills/` and `ontology/` are fetched from the in-tree
# knowledge folder by CI (`make skills`) before build.
COPY agent/pyproject.toml agent/README.md ./agent/
COPY agent/src ./agent/src
COPY agent/skills ./agent/skills
COPY agent/ontology ./agent/ontology
RUN pip install --no-cache-dir ./agent

ENV SKILLS_DIR=/app/agent/skills \
    ONTOLOGY_DIR=/app/agent/ontology \
    PYTHONUNBUFFERED=1

EXPOSE 8080

# Launch under opentelemetry-instrument so AgentCore Observability captures traces
# automatically (aws-opentelemetry-distro is installed above).
CMD ["opentelemetry-instrument", "python", "-m", "order_triage.runtime"]
