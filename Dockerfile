FROM python:3.12-slim
WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY scenarios ./scenarios
RUN pip install --no-cache-dir ".[mcp,langgraph,otel]" && rm -rf /src

# Mount your project at /work: docker run --rm -v "$PWD:/work" ghcr.io/sivram04/agent-reliability-lab run ...
RUN useradd --create-home arl
USER arl
WORKDIR /work
ENTRYPOINT ["arl"]
CMD ["--help"]
