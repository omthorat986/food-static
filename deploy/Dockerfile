# Production Container Image for Foodies Cloud Application
FROM python:3.12-slim

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    STORAGE_MODE=local \
    SECRET_KEY=foodies-cloud-production-secret-replace-me

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code and static assets
COPY . .

# Ensure upload, log, and database directories exist with proper permissions
RUN mkdir -p /app/logs /app/local_uploads && \
    chmod -R 755 /app

# Expose internal Gunicorn application port
EXPOSE 8080

# Healthcheck targeting the /health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 -c "import urllib.request; sys_exit = 0 if urllib.request.urlopen('http://127.0.0.1:8080/health').getcode() == 200 else 1; exit(sys_exit)"

# Launch WSGI server with 3 worker processes
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "3", "--threads", "2", "--timeout", "120", "--access-logfile", "-", "app:app"]
