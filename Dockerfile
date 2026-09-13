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
RUN ["npm", "ci"]
COPY frontend/ ./
RUN ["npm", "run", "build"]

# --- Stage 2: the actual runtime image ---
FROM python:3.12-slim AS runtime
WORKDIR /app

# Install system dependencies required for OpenCV and other edge ML libraries
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install full requirements since the container runs both edge and backend for the prototype demo
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY shared/ ./shared/
COPY edge/ ./edge/
COPY demo/ ./demo/
COPY certs/ ./certs/
COPY scripts/ ./scripts/
COPY start.sh ./
RUN chmod +x start.sh

COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# Ensure the data directories exist for the Render Disk mount
RUN mkdir -p /app/edge/data /app/demo/videos

ENV SERVER_HOST=0.0.0.0
ENV SERVER_PORT=8443
EXPOSE 8443

CMD ["./start.sh"]
