# Production Container Image for Foodies Application
FROM python:3.12-slim

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ENV=production \
    PORT=8080 \
    DATABASE_PATH=/var/lib/foodies/foodies.db \
    LOGS_DIR=/var/log/foodies

# Create foodies system user and group (mode 750)
RUN groupadd -g 1001 foodies && \
    useradd -u 1001 -g foodies -s /bin/bash -m foodies

WORKDIR /opt/foodies

# Install pinned dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code and static assets
COPY . .

# Ensure data and log directories exist outside webroot with mode 750
RUN mkdir -p /var/lib/foodies /var/log/foodies /opt/foodies/local_uploads && \
    chown -R foodies:foodies /opt/foodies /var/lib/foodies /var/log/foodies && \
    chmod 750 /opt/foodies /var/lib/foodies /var/log/foodies

USER foodies

EXPOSE 8080

# Container liveness check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 -c "import urllib.request; sys_exit = 0 if urllib.request.urlopen('http://127.0.0.1:8080/health').getcode() == 200 else 1; exit(sys_exit)"

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--threads", "2", "--timeout", "120", "--access-logfile", "/var/log/foodies/access.log", "--error-logfile", "/var/log/foodies/error.log", "app:app"]
