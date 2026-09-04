# NETRAKSH — single-container deploy image.
# Mirrors the app's real architecture (not a rewrite for containers): one
# FastAPI process serves both the API/WebSocket and the built React frontend
# from the same origin (backend/main.py's StaticFiles mount + catch-all),
# so this is one image, one process, one port — matching how the app has
# actually run throughout this project, not a new multi-service split.

# --- Stage 1: build the frontend ---
FROM node:20-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- Stage 2: the actual runtime image ---
FROM python:3.12-slim AS runtime
WORKDIR /app

# System deps for opencv-python-headless / ultralytics at import time
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY shared/ ./shared/
COPY edge/ ./edge/
COPY yolov8n.pt ./
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# Real secrets (SECRET_KEY, ADMIN_PASSWORD, DATABASE_URL, etc.) MUST be
# supplied by the hosting platform's environment variables at deploy time —
# see docs/LIMITATIONS.md's pre-live-deployment checklist. Nothing sensitive
# is baked into this image.
ENV SERVER_HOST=0.0.0.0
ENV SERVER_PORT=8443
EXPOSE 8443

CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8443"]
