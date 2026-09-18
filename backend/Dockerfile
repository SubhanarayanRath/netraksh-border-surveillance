FROM python:3.12-slim

WORKDIR /app

# Add non-root user
RUN groupadd -r netraksh && useradd -r -g netraksh netraksh

# Install OS dependencies if needed
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements-backend.txt .
RUN pip install --no-cache-dir -r requirements-backend.txt

# Copy backend and shared folders
COPY backend/ /app/backend/
COPY shared/ /app/shared/
COPY certs/ca/ /app/certs/ca/
COPY certs/server/ /app/certs/server/

# Set correct ownership for the non-root user
RUN chown -R netraksh:netraksh /app

USER netraksh

ENV PYTHONPATH=/app
ENV ENV=production

EXPOSE 8000

# Start Uvicorn
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
