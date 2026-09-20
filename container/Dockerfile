FROM cgr.dev/chainguard/python@sha256:011e73b4e30e0fe9407a42b82a920b4fa13ebc0bf029a48b714f950df254ca20
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app
COPY anvil /usr/local/bin/anvil
COPY entrotter_engine /app/entrotter_engine
WORKDIR /app
USER 65534:65534
ENTRYPOINT ["python3", "-m", "entrotter_engine._isolated_worker"]
