FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install .

RUN useradd --create-home --uid 10001 pipewatch
USER pipewatch

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request as u; u.urlopen('http://localhost:8000/healthz', timeout=3)"

CMD ["uvicorn", "pipewatch.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
