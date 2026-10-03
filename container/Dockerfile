FROM cgr.dev/chainguard/python@sha256:89281daac77a3d91ef298d70ce3b7a6ccb2ebf268c084fa9a9bda1c92e71c64d
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app
COPY anvil /usr/local/bin/anvil
COPY entrotter_engine /app/entrotter_engine
WORKDIR /app
USER 65534:65534
ENTRYPOINT ["python3", "-m", "entrotter_engine._isolated_worker"]
