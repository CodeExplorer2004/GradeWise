FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml langgraph.json ./
RUN --mount=type=cache,target=/root/.cache/pip \
    mkdir -p app && touch app/__init__.py && pip install .
COPY app ./app
RUN useradd --create-home --uid 10002 agentuser && chown -R agentuser:agentuser /app
USER agentuser
EXPOSE 2024
CMD ["langgraph", "dev", "--host", "0.0.0.0", "--port", "2024", "--no-browser", "--no-reload", "--n-jobs-per-worker", "4"]
