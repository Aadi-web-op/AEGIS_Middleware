# AEGIS backend (FastAPI) — container image for Hugging Face Spaces,
# Render, Railway or any Docker host.
#
#   docker build -t aegis-api .
#   docker run -p 7860:7860 -e GROQ_API_KEY=... aegis-api
#
# Hugging Face Spaces runs containers as UID 1000 and expects port 7860.
FROM python:3.12-slim

RUN useradd -m -u 1000 user
USER user

ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    HF_HOME=/home/user/.cache/huggingface \
    PYTHONUNBUFFERED=1 \
    PORT=7860

WORKDIR /home/user/app

# CPU-only torch first: avoids pulling ~2 GB of CUDA wheels.
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir --user -r requirements.txt

COPY --chown=user app ./app
COPY --chown=user aegis_core ./aegis_core
COPY --chown=user config ./config
COPY --chown=user data ./data

EXPOSE 7860
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-7860}"]
