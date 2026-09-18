FROM python:3.12-slim

WORKDIR /app

# Add non-root user
RUN groupadd -r netraksh && useradd -r -g netraksh netraksh

# Install OS dependencies for OpenCV (libgl1, libglib2.0-0)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install Edge dependencies
COPY edge/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY edge/ /app/edge/
COPY shared/ /app/shared/
# We do NOT copy certs/ or demo/ into the image. They must be bind-mounted.

# Ensure data directory exists and has correct permissions
RUN mkdir -p /app/edge/data /app/certs
RUN chown -R netraksh:netraksh /app

# Run as non-root
USER netraksh

# Set correct pythonpath
ENV PYTHONPATH=/app
ENV ENV=production

# Explicit production entrypoint (not demo_runner.py)
CMD ["python", "edge/main.py"]
