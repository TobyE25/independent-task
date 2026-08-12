# Cloud Run Job image. One image, several jobs — each Cloud Run Job overrides the command to run a
# different pipeline step, so there is one artefact to build, scan and promote rather than four.
#
# slim, not alpine: alpine's musl libc has no manylinux wheels for pyarrow, so it would compile
# Arrow from source and turn a 40-second build into a 20-minute one.
FROM python:3.12-slim

# Non-root. Cloud Run does not require it, but a container that cannot write outside its own
# workspace is one less thing to reason about if the image is ever reused somewhere less isolated.
RUN useradd --create-home --uid 1001 pipeline

WORKDIR /app

# Dependencies before source, so a code change does not invalidate the dependency layer.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY pipeline/ ./pipeline/
COPY dbt/ ./dbt/
COPY tools/ ./tools/

USER pipeline

# No secrets baked in. PSEUDONYM_HMAC_KEY arrives from Secret Manager at runtime via
# --set-secrets, and config.py refuses to start without it — so a misconfigured deployment fails
# immediately rather than emitting predictable pseudonyms that look correct.
ENV PYTHONUNBUFFERED=1 \
    TARGET=gcp

# Overridden per job. Defaults to the sales load because that is the step that shards.
ENTRYPOINT ["python", "-m", "pipeline.cli"]
CMD ["ingest-sales"]
