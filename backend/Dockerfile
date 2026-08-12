FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y gcc g++ libpq-dev curl && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# The language model is hosted on GitHub, which is intermittently unavailable
# from managed Docker builders. Keep production builds reliable by making the
# optional model opt-in; PIIRedactor logs and uses its regex fallback otherwise.
ARG INSTALL_SPACY_MODEL=false
RUN if [ "$INSTALL_SPACY_MODEL" = "true" ]; then python -m spacy download en_core_web_sm; fi
RUN groupadd --system appgroup && useradd --system --gid appgroup --create-home appuser \
    && mkdir -p /app/chroma_db /app/uploads \
    && chown -R appuser:appgroup /app
COPY --chown=appuser:appgroup . .
USER appuser
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
