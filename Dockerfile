FROM python:3.12-slim
WORKDIR /lab
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[mcp,langgraph,otel]"
COPY fixtures ./fixtures
COPY scenarios ./scenarios
ENTRYPOINT ["arl"]
CMD ["--help"]
