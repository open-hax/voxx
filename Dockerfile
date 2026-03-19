# syntax=docker/dockerfile:1.7

ARG VOXX_BASE_IMAGE=localhost:5000/openhax/melo-voice-base:2026-03-19
FROM ${VOXX_BASE_IMAGE}

USER root
WORKDIR /app

COPY src /app/src
COPY README.md requirements.txt .env.example package.json /app/

ENV PYTHONPATH=/app/src
ENV VOICE_GATEWAY_DATA_DIR=/app/data
ENV VOICE_GATEWAY_HOST=0.0.0.0
ENV VOICE_GATEWAY_PORT=8788

RUN mkdir -p /app/data \
    && chown -R appuser:appuser /app

EXPOSE 8788

USER appuser
CMD ["python3", "-m", "voice_gateway"]
