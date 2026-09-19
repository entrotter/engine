FROM python:3.12-slim-trixie@sha256:2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app
COPY anvil /usr/local/bin/anvil
COPY entrotter_engine /app/entrotter_engine
WORKDIR /app
USER 65534:65534
ENTRYPOINT ["python", "-m", "entrotter_engine._isolated_worker"]
