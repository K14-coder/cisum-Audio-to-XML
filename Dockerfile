# One image for the API and the worker. Build with ML backends (default) or without:
#   docker build -t cisum .
#   docker build --build-arg WITH_ML=0 -t cisum-lite .

FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libsndfile1 libcairo2 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/pyproject.toml backend/README.md backend/requirements-ml.txt ./
COPY backend/cisum ./cisum
ARG WITH_ML=1
# CPU PyTorch wheels keep the image small; swap the index for a CUDA one on GPU workers.
ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir ".[postgres]" \
    && if [ "$WITH_ML" = "1" ]; then \
         pip install --no-cache-dir --extra-index-url "$TORCH_INDEX" ".[ml]" \
         && pip install --no-cache-dir --no-deps -r requirements-ml.txt; \
       fi
COPY --from=web /web/dist /app/web/dist
ENV CISUM_WEB_DIST=/app/web/dist \
    PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "cisum.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
