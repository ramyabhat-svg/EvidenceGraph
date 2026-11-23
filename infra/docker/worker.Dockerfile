FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt requirements-api.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-api.txt \
    && python -m spacy download en_core_web_sm-3.8.0 --direct \
    && useradd --create-home --uid 10001 app

COPY --chown=app:app eg_common ./eg_common
COPY --chown=app:app persistence ./persistence
COPY --chown=app:app worker ./worker
COPY --chown=app:app domain ./domain
COPY --chown=app:app domain_packs ./domain_packs

USER app

CMD ["python", "-m", "worker.main"]
