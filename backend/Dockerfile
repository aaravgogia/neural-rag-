FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y gcc g++ libpq-dev curl && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Presidio uses this model for named-entity recognition.  Installing it during
# the full production image build avoids a silent regex-only fallback at first
# ingestion when PII_REDACTION_ENABLED=true.
RUN python -m spacy download en_core_web_sm
RUN groupadd --system appgroup && useradd --system --gid appgroup --create-home appuser \
    && mkdir -p /app/chroma_db /app/uploads \
    && chown -R appuser:appgroup /app
COPY --chown=appuser:appgroup . .
USER appuser
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
