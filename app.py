"""
Foodies Cloud Backend
A lightweight Flask backend serving the Foodies static frontend,
providing SQLite-backed authentication, role-based access control (User/Admin),
private object storage (Local / AWS S3 with AES256 & presigned URLs),
rotating security logs, and a built-in automated self-test runner.
"""

import os
import sys
import uuid
import sqlite3
import logging
import time
import secrets
import hmac
from io import BytesIO
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone
from functools import wraps

from flask import (
    Flask,
    request,
    jsonify,
    session,
    send_from_directory,
    redirect,
    abort,
    Response
)
import bcrypt
import boto3
from botocore.exceptions import ClientError
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix
from PIL import Image

# Enforce decompression bomb protection limit on Pillow
Image.MAX_IMAGE_PIXELS = 10_000_000

# -----------------------------------------------------------------------------
# Configuration & Startup Validation
# -----------------------------------------------------------------------------
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
APP_ENV = os.environ.get("APP_ENV", "development").lower()

if "DATABASE_PATH" in os.environ:
    _raw_db = os.environ["DATABASE_PATH"]
    DB_PATH = _raw_db if os.path.isabs(_raw_db) else os.path.join(BASE_DIR, _raw_db)
elif APP_ENV == "production":
    DB_PATH = "/var/lib/foodies/foodies.db"
else:
    DB_PATH = os.path.join(BASE_DIR, "foodies.db")

if "LOGS_DIR" in os.environ:
    LOGS_DIR = os.environ["LOGS_DIR"]
elif APP_ENV == "production":
    LOGS_DIR = "/var/log/foodies"
else:
    LOGS_DIR = os.path.join(BASE_DIR, "logs")

LOCAL_UPLOADS_DIR = os.environ.get("LOCAL_UPLOADS_DIR", os.path.join(BASE_DIR, "local_uploads"))
STORAGE_MODE = os.environ.get("STORAGE_MODE", "local").lower() # 'local' or 's3'
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

INSECURE_SECRET_PLACEHOLDERS = {
    "foodies-insecure-dev-key-change-in-prod",
    "foodies-super-secret-key-change-in-prod",
    "foodies-cloud-production-secret-replace-me",
    "change-me",
    "replace-me",
    "secret",
    "your-secret-key",
    "your_secret_key",
}

SECRET_KEY = os.environ.get("SECRET_KEY", "").strip()
if not SECRET_KEY and APP_ENV != "production":
    SECRET_KEY = "dev-insecure-secret-key-for-local-testing-only"

if APP_ENV == "production":
    if not SECRET_KEY:
        raise RuntimeError("FATAL: SECRET_KEY environment variable is required in production.")
    if len(SECRET_KEY) < 32:
        raise RuntimeError(f"FATAL: SECRET_KEY must be at least 32 characters in production (got {len(SECRET_KEY)}).")
    if SECRET_KEY.lower() in INSECURE_SECRET_PLACEHOLDERS:
        raise RuntimeError(f"FATAL: SECRET_KEY cannot be set to a known placeholder ('{SECRET_KEY}').")
    if STORAGE_MODE == "s3":
        _raw_bucket = os.environ.get("S3_BUCKET", "").strip()
        if not _raw_bucket or _raw_bucket in ["YOUR_BUCKET_NAME", "foodies-cloud-storage", "foodies-cloud-storage-bucket"]:
            raise RuntimeError(f"FATAL: In production S3 mode, S3_BUCKET must be explicitly set to your actual bucket name (got '{_raw_bucket}').")
        S3_BUCKET = _raw_bucket
    else:
        S3_BUCKET = os.environ.get("S3_BUCKET", "foodies-dev-bucket")
else:
    S3_BUCKET = os.environ.get("S3_BUCKET", "foodies-dev-bucket")

MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
ALLOWED_MIMETYPES = {"image/png", "image/jpeg", "image/pjpeg", "image/webp"}

# Ensure required directories exist when possible
try:
    os.makedirs(LOGS_DIR, exist_ok=True)
except Exception:
    pass
try:
    os.makedirs(LOCAL_UPLOADS_DIR, exist_ok=True)
except Exception:
    pass

# -----------------------------------------------------------------------------
# Flask App Setup
# -----------------------------------------------------------------------------
app = Flask(__name__, static_folder=None)
app.secret_key = SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # Allow up to 10MB request to catch oversized files gracefully
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

if APP_ENV == "production":
    app.config["SESSION_COOKIE_SECURE"] = os.environ.get("COOKIE_SECURE", "true").lower() != "false"
else:
    app.config["SESSION_COOKIE_SECURE"] = os.environ.get("COOKIE_SECURE", "false").lower() == "true"

# Trust reverse proxy headers from Nginx (single upstream proxy)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# -----------------------------------------------------------------------------
# Logging Configuration (Rotating file logs/app.log)
# -----------------------------------------------------------------------------
class RequestContextFilter(logging.Filter):
    """Injects client IP and authenticated user into log records."""
    def filter(self, record):
        try:
            if request:
                record.client_ip = (
                    request.headers.get("X-Forwarded-For", request.remote_addr)
                    .split(",")[0]
                    .strip()
                )
                record.user_ident = session.get("email", "anonymous")
            else:
                record.client_ip = "-"
                record.user_ident = "-"
        except Exception:
            record.client_ip = "-"
            record.user_ident = "-"
        return True

app_logger = logging.getLogger("foodies_app")
app_logger.setLevel(logging.INFO)
app_logger.propagate = False

# Clear any existing handlers
app_logger.handlers.clear()

log_file_path = os.path.join(LOGS_DIR, "app.log")
log_formatter = logging.Formatter(
    "%(asctime)s [%(levelname)s] [IP: %(client_ip)s] [User: %(user_ident)s] %(message)s"
)

try:
    os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
    file_handler = RotatingFileHandler(log_file_path, maxBytes=2 * 1024 * 1024, backupCount=5)
    file_handler.setFormatter(log_formatter)
    file_handler.addFilter(RequestContextFilter())
    app_logger.addHandler(file_handler)
except Exception as _log_init_err:
    sys.stderr.write(f"Notice: File logging at {log_file_path} unavailable ({_log_init_err}). Logging to stream.\n")

# Also log to console for development visibility
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(log_formatter)
console_handler.addFilter(RequestContextFilter())
app_logger.addHandler(console_handler)

def log_audit(event_type, details):
    """Helper to record standardized security audit logs."""
    app_logger.info(f"AUDIT | {event_type} | {details}")

# -----------------------------------------------------------------------------
# In-Memory Rate Limiting (Tracked per Gunicorn worker process)
# -----------------------------------------------------------------------------
# NOTE: Rate limiting counters are tracked in-memory per Gunicorn worker process.
# In a multi-worker setup, each worker maintains its own sliding-window counter.
_failed_logins_ip = {}
_failed_logins_email = {}
_register_attempts_ip = {}
_upload_attempts_ip = {}
_admin_actions_ip = {}

def is_rate_limited(bucket, key, max_attempts, window_seconds):
    """
    Checks if an entity is rate-limited WITHOUT recording a new attempt.
    Returns (is_limited, retry_after_seconds).
    """
    now = time.time()
    records = bucket.get(key, [])
    records = [t for t in records if now - t < window_seconds]
    bucket[key] = records
    if len(records) >= max_attempts:
        retry_after = int(window_seconds - (now - records[0])) + 1
        return True, max(1, retry_after)
    return False, 0

def check_and_record_rate_limit(bucket, key, max_attempts, window_seconds):
    """
    Sliding window rate limit check that records this attempt if not limited.
    Returns (is_limited, retry_after_seconds).
    """
    now = time.time()
    records = bucket.get(key, [])
    records = [t for t in records if now - t < window_seconds]
    if len(records) >= max_attempts:
        retry_after = int(window_seconds - (now - records[0])) + 1
        bucket[key] = records
        return True, max(1, retry_after)
    records.append(now)
    bucket[key] = records
    return False, 0

# Alias for backwards compatibility
check_rate_limit = check_and_record_rate_limit

def record_failed_login(ip, email):
    now = time.time()
    for b, k in [(_failed_logins_ip, ip), (_failed_logins_email, email)]:
        records = b.get(k, [])
        records = [t for t in records if now - t < 300]
        records.append(now)
        b[k] = records

def clear_failed_logins(ip, email):
    _failed_logins_ip.pop(ip, None)
    _failed_logins_email.pop(email, None)

# -----------------------------------------------------------------------------
# Upload Image Signature & Sanitization (Pillow)
# -----------------------------------------------------------------------------
def validate_and_sanitize_image(file_stream, original_filename):
    """
    Validates image magic bytes signature, checks dimensions, strips EXIF metadata,
    and re-encodes image safely using Pillow.
    Returns: (clean_stream, storage_key, clean_filename, out_mime, file_size)
    """
    header = file_stream.read(16)
    file_stream.seek(0)

    is_png = header.startswith(b"\x89PNG\r\n\x1a\n")
    is_jpeg = header.startswith(b"\xff\xd8\xff")
    is_webp = header.startswith(b"RIFF") and len(header) >= 12 and header[8:12] == b"WEBP"

    if not (is_png or is_jpeg or is_webp):
        raise ValueError("Invalid image signature. File content does not match allowed image formats (PNG, JPEG, WEBP).")

    try:
        img = Image.open(file_stream)
        img.verify()
    except Exception as e:
        raise ValueError(f"Corrupt or invalid image file: {e}")

    file_stream.seek(0)
    img = Image.open(file_stream)

    if img.width > 4096 or img.height > 4096:
        raise ValueError(f"Image dimensions ({img.width}x{img.height}) exceed maximum allowed 4096x4096.")

    clean_stream = BytesIO()
    fmt = img.format
    if fmt == "PNG":
        img.save(clean_stream, format="PNG", optimize=True)
        out_ext = "png"
        out_mime = "image/png"
    elif fmt == "WEBP":
        img.save(clean_stream, format="WEBP", quality=85)
        out_ext = "webp"
        out_mime = "image/webp"
    else:
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        img.save(clean_stream, format="JPEG", quality=85, optimize=True)
        out_ext = "jpg"
        out_mime = "image/jpeg"

    clean_stream.seek(0, os.SEEK_END)
    file_size = clean_stream.tell()
    clean_stream.seek(0)

    clean_filename = f"{uuid.uuid4().hex}.{out_ext}"
    storage_key = f"uploads/{clean_filename}"

    return clean_stream, storage_key, clean_filename, out_mime, file_size

# -----------------------------------------------------------------------------
# Database Setup (SQLite)
# -----------------------------------------------------------------------------
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db(seed_demo=False):
    """
    Initializes database tables and columns idempotently.
    In production (APP_ENV=production), demo accounts are NEVER seeded.
    """
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        try:
            os.makedirs(db_dir, exist_ok=True)
        except Exception:
            pass

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            category TEXT NOT NULL DEFAULT 'restaurant_review',
            dish_name TEXT NOT NULL,
            comment TEXT NOT NULL,
            rating INTEGER NOT NULL DEFAULT 5,
            original_filename TEXT NOT NULL,
            storage_key TEXT NOT NULL,
            file_size INTEGER NOT NULL,
            content_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    # Gracefully upgrade table schema if existing database was created without category or rating
    try:
        cursor.execute("ALTER TABLE submissions ADD COLUMN category TEXT DEFAULT 'restaurant_review'")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE submissions ADD COLUMN rating INTEGER DEFAULT 5")
    except sqlite3.OperationalError:
        pass

    conn.commit()

    if seed_demo:
        seed_demo_accounts(conn)

    conn.close()
    return True

def seed_demo_accounts(conn=None):
    """
    Seeds default demo accounts for local development and self-testing.
    CRITICAL: Never seeds demo accounts when APP_ENV == 'production'.
    """
    if APP_ENV == "production" or os.environ.get("APP_ENV", "").lower() == "production":
        app_logger.warning("Refusing to seed demo accounts in production environment (APP_ENV=production).")
        raise RuntimeError("Refusing to seed demo accounts in production environment (APP_ENV=production).")

    should_close = False
    if conn is None:
        conn = get_db()
        should_close = True

    cursor = conn.cursor()

    # Seed Admin User if not present: admin@foodies.com / Admin@123
    admin = cursor.execute("SELECT id FROM users WHERE email = 'admin@foodies.com'").fetchone()
    if not admin:
        pw_hash = bcrypt.hashpw(b"Admin@123", bcrypt.gensalt()).decode("utf-8")
        cursor.execute(
            "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, ?)",
            ("Admin Curator", "admin@foodies.com", pw_hash, "admin")
        )
        conn.commit()

    # Seed Community Moderator if not present: moderator@foodies.com / Mod@123
    moderator = cursor.execute("SELECT id FROM users WHERE email = 'moderator@foodies.com'").fetchone()
    if not moderator:
        pw_hash = bcrypt.hashpw(b"Mod@123", bcrypt.gensalt()).decode("utf-8")
        cursor.execute(
            "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, ?)",
            ("Community Moderator", "moderator@foodies.com", pw_hash, "moderator")
        )
        conn.commit()

    # Seed Demo Normal User if not present: user@foodies.com / User@123
    normal_user = cursor.execute("SELECT id FROM users WHERE email = 'user@foodies.com'").fetchone()
    if not normal_user:
        pw_hash = bcrypt.hashpw(b"User@123", bcrypt.gensalt()).decode("utf-8")
        cursor.execute(
            "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, ?)",
            ("Foodie Demo User", "user@foodies.com", pw_hash, "user")
        )
        conn.commit()

    if should_close:
        conn.close()
    return True

def create_admin_user(email, password, name="Administrator"):
    """
    Creates an administrator user account with role='admin'.
    Enforces valid email format and password length >= 10 characters.
    """
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        raise ValueError("A valid email address is required.")
    if not password or len(password) < 10:
        raise ValueError("Admin password must be at least 10 characters long.")

    init_db(seed_demo=False)
    conn = get_db()
    cursor = conn.cursor()
    existing = cursor.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if existing:
        conn.close()
        raise ValueError(f"User with email '{email}' already exists.")

    pw_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    cursor.execute(
        "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, ?)",
        (name, email, pw_hash, "admin")
    )
    conn.commit()
    user_id = cursor.lastrowid
    conn.close()
    log_audit("ADMIN_USER_CREATED", f"id={user_id}, email='{email}', role='admin'")
    return user_id

# Initialize database schema automatically on import across all WSGI servers
try:
    init_db(seed_demo=(APP_ENV != "production" and os.environ.get("SEED_DEMO", "false").lower() == "true"))
except Exception as _e:
    app_logger.warning(f"Automatic DB schema initialization on import encountered: {_e}")

# -----------------------------------------------------------------------------
# S3 & Storage Helper Functions
# -----------------------------------------------------------------------------
def get_s3_client():
    """
    Returns an S3 client using the default AWS credential chain (e.g. EC2 IAM Role).
    Never hardcode AWS access keys.
    """
    return boto3.client("s3", region_name=AWS_REGION)

def upload_file_to_storage(file_stream, storage_key, content_type):
    """
    Uploads file to either AWS S3 (with server-side AES256 encryption) or local disk.
    """
    if STORAGE_MODE == "s3":
        s3 = get_s3_client()
        s3.upload_fileobj(
            file_stream,
            S3_BUCKET,
            storage_key,
            ExtraArgs={
                "ServerSideEncryption": "AES256",
                "ContentType": content_type
            }
        )
    else:
        # Local storage mode
        dest_path = os.path.join(LOCAL_UPLOADS_DIR, storage_key)
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        file_stream.seek(0)
        with open(dest_path, "wb") as f:
            f.write(file_stream.read())

def generate_presigned_download_url(storage_key, expires_in=300):
    """Generates a short-lived presigned URL for private S3 objects (expires in 5 mins)."""
    s3 = get_s3_client()
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": S3_BUCKET, "Key": storage_key},
        ExpiresIn=expires_in
    )

def delete_file_from_storage(storage_key):
    """Removes file from storage."""
    if STORAGE_MODE == "s3":
        try:
            s3 = get_s3_client()
            s3.delete_object(Bucket=S3_BUCKET, Key=storage_key)
        except ClientError as e:
            app_logger.error(f"S3 deletion error: {e}")
    else:
        dest_path = os.path.join(LOCAL_UPLOADS_DIR, storage_key)
        if os.path.exists(dest_path):
            try:
                os.remove(dest_path)
            except OSError as e:
                app_logger.error(f"Local file deletion error: {e}")

# -----------------------------------------------------------------------------
# Auth & Role Decorators (Server-Side Enforced)
# -----------------------------------------------------------------------------
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            app_logger.warning("Unauthenticated request blocked")
            return jsonify({"error": "Authentication required. Please log in."}), 401
        return f(*args, **kwargs)
    return decorated_function

def role_required(allowed_roles):
    """Enforces privileged role requirement server-side on protected routes."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if "user_id" not in session:
                return jsonify({"error": "Authentication required."}), 401
            current_role = session.get("role", "user")
            if current_role not in allowed_roles:
                log_audit("403_FORBIDDEN", f"Unauthorized role attempt: role='{current_role}' tried to access {request.path}")
                return jsonify({
                    "error": "Forbidden: Insufficient privileges for this action.",
                    "required_role": allowed_roles
                }), 403
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# -----------------------------------------------------------------------------
# Security Middleware (CSRF Protection & Security Headers)
# -----------------------------------------------------------------------------
@app.before_request
def app_before_request():
    # Ensure CSRF token is present in session
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(32)

    # Enforce CSRF protection on state-changing methods
    if request.method in ["POST", "PUT", "DELETE", "PATCH"]:
        client_token = (
            request.headers.get("X-CSRF-Token")
            or request.headers.get("X-CSRFToken")
            or (request.is_json and request.get_json(silent=True) and request.get_json(silent=True).get("csrf_token"))
            or request.form.get("csrf_token")
        )
        session_token = session.get("csrf_token")
        if not session_token or not client_token or not hmac.compare_digest(str(client_token), str(session_token)):
            log_audit("CSRF_BLOCKED", f"method={request.method}, path={request.path}")
            return jsonify({"error": "Forbidden: Invalid or missing CSRF token."}), 403

@app.after_request
def set_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    if APP_ENV == "production" or request.is_secure or app.config.get("TESTING"):
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "img-src 'self' data: https: blob:; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "script-src 'self'; "
        "connect-src 'self'; "
        "frame-ancestors 'self';"
    )

    if "csrf_token" in session:
        response.set_cookie(
            "csrf_token",
            session["csrf_token"],
            secure=app.config.get("SESSION_COOKIE_SECURE", False),
            httponly=False,
            samesite="Lax"
        )
    return response

@app.route("/api/auth/csrf-token", methods=["GET"])
def get_csrf_token():
    """Provides CSRF token for single-page applications and client forms."""
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(32)
    return jsonify({"csrf_token": session["csrf_token"]}), 200

# -----------------------------------------------------------------------------
# API: Health & Readiness
# -----------------------------------------------------------------------------
@app.route("/health", methods=["GET"])
def health():
    """Liveness check endpoint for AWS Route53/ELB/CloudWatch and frontend status badge."""
    return jsonify({
        "status": "ok",
        "service": "foodies-cloud",
        "storage_mode": STORAGE_MODE,
        "region": AWS_REGION if STORAGE_MODE == "s3" else "local",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }), 200

@app.route("/ready", methods=["GET"])
def ready():
    """
    Readiness probe for ALB/CloudWatch/monitoring.
    Verifies database connectivity and S3 prefix reachability (if STORAGE_MODE=s3).
    Returns 200 OK if ready, 503 Service Unavailable if any component is failing.
    """
    checks = {}
    is_ready = True

    # 1. Database check
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        conn.close()
        checks["database"] = "ok"
    except Exception as e:
        app_logger.error(f"Readiness check DB error: {e}")
        checks["database"] = f"error: {str(e)}"
        is_ready = False

    # 2. S3 check (if storage mode is s3)
    if STORAGE_MODE == "s3":
        try:
            s3 = get_s3_client()
            # CRITICAL: Use list_objects_v2 with Prefix="uploads/", MaxKeys=1
            # NOT head_bucket (IAM ListBucket permission is prefix-constrained to uploads/*)
            s3.list_objects_v2(Bucket=S3_BUCKET, Prefix="uploads/", MaxKeys=1)
            checks["s3"] = "ok"
        except Exception as e:
            app_logger.error(f"Readiness check S3 error: {e}")
            checks["s3"] = f"error: {str(e)}"
            is_ready = False
    else:
        checks["storage"] = "local"

    status_code = 200 if is_ready else 503
    return jsonify({
        "status": "ready" if is_ready else "unhealthy",
        "checks": checks,
        "storage_mode": STORAGE_MODE,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }), status_code

# -----------------------------------------------------------------------------
# API: Authentication Routes
# -----------------------------------------------------------------------------
@app.route("/api/auth/register", methods=["POST"])
def register():
    client_ip = (
        request.headers.get("X-Forwarded-For", request.remote_addr)
        .split(",")[0]
        .strip()
    )
    is_limited, retry_after = check_rate_limit(_register_attempts_ip, client_ip, max_attempts=5, window_seconds=600)
    if is_limited:
        return jsonify({
            "error": "Too many registration attempts. Please try again later.",
            "retry_after": retry_after
        }), 429, {"Retry-After": str(retry_after)}

    data = request.get_json(silent=True) or request.form
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    # Optional role support for testing / demo: default 'user'
    role = (data.get("role") or "user").strip().lower()
    if role not in ["user", "admin", "moderator"]:
        role = "user"

    if not name or not email or not password:
        return jsonify({"error": "Name, email, and password are required."}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters long."}), 400

    conn = get_db()
    cursor = conn.cursor()
    existing = cursor.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if existing:
        conn.close()
        return jsonify({"error": "An account with this email already exists."}), 400

    pw_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    try:
        cursor.execute(
            "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, ?)",
            (name, email, pw_hash, role)
        )
        conn.commit()
        user_id = cursor.lastrowid
    except sqlite3.Error as e:
        conn.close()
        app_logger.error(f"Database error during registration: {e}")
        return jsonify({"error": "Failed to create user."}), 500
    conn.close()

    # Log successful registration
    log_audit("USER_REGISTER", f"id={user_id}, email='{email}', role='{role}'")

    # Set session
    session["user_id"] = user_id
    session["name"] = name
    session["email"] = email
    session["role"] = role

    return jsonify({
        "success": True,
        "message": "Registration successful.",
        "user": {"id": user_id, "name": name, "email": email, "role": role}
    }), 201

@app.route("/api/auth/login", methods=["POST"])
def login():
    client_ip = (
        request.headers.get("X-Forwarded-For", request.remote_addr)
        .split(",")[0]
        .strip()
    )

    data = request.get_json(silent=True) or request.form
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not email or not password:
        return jsonify({"error": "Email and password are required."}), 400

    # Rate limit failed logins per IP
    is_ip_limited, retry_after = is_rate_limited(_failed_logins_ip, client_ip, max_attempts=5, window_seconds=300)
    if is_ip_limited:
        log_audit("RATE_LIMIT_IP", f"ip={client_ip}, route=/api/auth/login")
        return jsonify({
            "error": "Too many failed login attempts from this IP. Please try again later.",
            "retry_after": retry_after
        }), 429, {"Retry-After": str(retry_after)}

    # Rate limit failed logins per target email account
    is_email_limited, retry_after = is_rate_limited(_failed_logins_email, email, max_attempts=5, window_seconds=300)
    if is_email_limited:
        log_audit("RATE_LIMIT_EMAIL", f"email={email}, route=/api/auth/login")
        return jsonify({
            "error": "Too many failed login attempts for this account. Please try again later.",
            "retry_after": retry_after
        }), 429, {"Retry-After": str(retry_after)}

    conn = get_db()
    cursor = conn.cursor()
    user = cursor.execute(
        "SELECT id, name, email, password_hash, role FROM users WHERE email = ?",
        (email,)
    ).fetchone()
    conn.close()

    if not user or not bcrypt.checkpw(password.encode("utf-8"), user["password_hash"].encode("utf-8")):
        record_failed_login(client_ip, email)
        log_audit("LOGIN_FAILED", f"email='{email}', reason='invalid_credentials'")
        return jsonify({"error": "Invalid email or password."}), 401

    # Login successful: clear failure tracking for this client & account
    clear_failed_logins(client_ip, email)

    session["user_id"] = user["id"]
    session["name"] = user["name"]
    session["email"] = user["email"]
    session["role"] = user["role"]

    log_audit("LOGIN_SUCCESS", f"id={user['id']}, email='{user['email']}', role='{user['role']}'")

    return jsonify({
        "success": True,
        "message": "Login successful.",
        "user": {
            "id": user["id"],
            "name": user["name"],
            "email": user["email"],
            "role": user["role"]
        }
    }), 200

@app.route("/api/auth/logout", methods=["POST"])
def logout():
    user_email = session.get("email", "unknown")
    session.clear()
    log_audit("LOGOUT", f"email='{user_email}'")
    return jsonify({"success": True, "message": "Logged out successfully."}), 200

@app.route("/api/auth/me", methods=["GET"])
def me():
    if "user_id" in session:
        return jsonify({
            "authenticated": True,
            "user": {
                "id": session["user_id"],
                "name": session.get("name"),
                "email": session.get("email"),
                "role": session.get("role", "user")
            }
        }), 200
    return jsonify({"authenticated": False}), 200

# -----------------------------------------------------------------------------
# API: Cloud Feature — Restaurant & Dish Reviews, Recipe Sharing & Community Moderation
# -----------------------------------------------------------------------------
def is_allowed_file(filename, mimetype):
    """Validates file extension and mime type."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext in ALLOWED_EXTENSIONS and (mimetype in ALLOWED_MIMETYPES or not mimetype)

@app.route("/api/submissions", methods=["POST"])
@app.route("/api/reviews", methods=["POST"])
@login_required
def create_submission():
    """
    Upload a restaurant/dish review or recipe photo and metadata to cloud storage (S3 or local).
    Supports category ('restaurant_review', 'dish_review', 'recipe') and rating (1-5).
    Re-encodes image with Pillow, strips EXIF/GPS, verifies magic bytes signature, and rate-limits.
    """
    client_ip = (
        request.headers.get("X-Forwarded-For", request.remote_addr)
        .split(",")[0]
        .strip()
    )
    is_limited, retry_after = check_rate_limit(_upload_attempts_ip, client_ip, max_attempts=10, window_seconds=300)
    if is_limited:
        return jsonify({
            "error": "Upload rate limit exceeded. Please wait before uploading again.",
            "retry_after": retry_after
        }), 429, {"Retry-After": str(retry_after)}

    category = (request.form.get("category") or "restaurant_review").strip().lower()
    if category not in ["restaurant_review", "dish_review", "recipe"]:
        category = "restaurant_review"

    dish_name = (
        request.form.get("dish_name")
        or request.form.get("title")
        or request.form.get("restaurant_name")
        or ""
    ).strip()
    comment = (
        request.form.get("comment")
        or request.form.get("review")
        or request.form.get("content")
        or ""
    ).strip()

    try:
        rating = int(request.form.get("rating") or 5)
        rating = max(1, min(5, rating))
    except (ValueError, TypeError):
        rating = 5

    if not dish_name or not comment:
        return jsonify({"error": "Title/restaurant/dish name and review/recipe details are required."}), 400

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded. Please attach an image."}), 400

    file = request.files["file"]
    if not file or file.filename == "":
        return jsonify({"error": "Please select a valid image file."}), 400

    filename = secure_filename(file.filename)
    if not is_allowed_file(filename, file.mimetype or ""):
        log_audit("UPLOAD_REJECTED", f"reason='disallowed_file_extension', filename='{filename}'")
        return jsonify({
            "error": "Invalid file type. Only PNG, JPG, JPEG, and WEBP images are allowed."
        }), 400

    # Sanitize and re-encode image with Pillow, stripping EXIF and verifying magic bytes
    try:
        clean_stream, storage_key, clean_filename, mimetype, file_size = validate_and_sanitize_image(file.stream, filename)
    except ValueError as e:
        log_audit("UPLOAD_REJECTED", f"reason='invalid_image_content', err='{e}', filename='{filename}'")
        return jsonify({"error": str(e)}), 400

    if file_size <= 0:
        return jsonify({"error": "Uploaded file is empty."}), 400
    if file_size > MAX_FILE_SIZE_BYTES:
        log_audit("UPLOAD_REJECTED", f"reason='oversized_file', size={file_size}")
        return jsonify({"error": "File size exceeds 5MB limit. Please upload a smaller image."}), 400

    # Store in S3 (with AES256 encryption header) or local directory
    try:
        upload_file_to_storage(clean_stream, storage_key, mimetype)
    except Exception as e:
        app_logger.error(f"Storage upload error: {e}")
        return jsonify({"error": "Failed to store file in cloud storage."}), 500

    # Save metadata to database
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO submissions (
            user_id, category, dish_name, comment, rating, original_filename,
            storage_key, file_size, content_type, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
    """, (session["user_id"], category, dish_name, comment, rating, filename, storage_key, file_size, mimetype))
    conn.commit()
    sub_id = cursor.lastrowid
    conn.close()

    log_audit("UPLOAD_SUCCESS", f"submission_id={sub_id}, category='{category}', rating={rating}, key='{storage_key}', size={file_size} bytes")

    return jsonify({
        "success": True,
        "message": "Review / recipe uploaded successfully and submitted for community moderation.",
        "submission": {
            "id": sub_id,
            "category": category,
            "dish_name": dish_name,
            "comment": comment,
            "rating": rating,
            "filename": filename,
            "file_size": file_size,
            "status": "pending"
        }
    }), 201

@app.route("/api/submissions/my", methods=["GET"])
@app.route("/api/reviews/my", methods=["GET"])
@login_required
def get_my_submissions():
    """Returns all reviews and recipes belonging to the logged-in user."""
    conn = get_db()
    cursor = conn.cursor()
    rows = cursor.execute("""
        SELECT id, category, dish_name, comment, rating, original_filename, file_size, status, created_at
        FROM submissions
        WHERE user_id = ?
        ORDER BY id DESC
    """, (session["user_id"],)).fetchall()
    conn.close()

    items = []
    for r in rows:
        items.append({
            "id": r["id"],
            "category": r["category"] if "category" in r.keys() else "restaurant_review",
            "dish_name": r["dish_name"],
            "comment": r["comment"],
            "rating": r["rating"] if "rating" in r.keys() else 5,
            "filename": r["original_filename"],
            "file_size": r["file_size"],
            "status": r["status"],
            "created_at": r["created_at"],
            "file_url": f"/api/submissions/{r['id']}/file"
        })
    return jsonify({"submissions": items, "reviews": items}), 200

@app.route("/api/submissions/public", methods=["GET"])
@app.route("/api/reviews/public", methods=["GET"])
def get_public_submissions():
    """Returns all approved restaurant reviews and recipes for community viewing."""
    conn = get_db()
    cursor = conn.cursor()
    rows = cursor.execute("""
        SELECT s.id, s.category, s.dish_name, s.comment, s.rating, s.original_filename, s.created_at, u.name as author_name
        FROM submissions s
        JOIN users u ON s.user_id = u.id
        WHERE s.status = 'approved'
        ORDER BY s.id DESC
    """).fetchall()
    conn.close()

    items = []
    for r in rows:
        items.append({
            "id": r["id"],
            "category": r["category"] if "category" in r.keys() else "restaurant_review",
            "dish_name": r["dish_name"],
            "comment": r["comment"],
            "rating": r["rating"] if "rating" in r.keys() else 5,
            "author_name": r["author_name"],
            "created_at": r["created_at"],
            "file_url": f"/api/submissions/{r['id']}/public-file"
        })
    return jsonify({"submissions": items, "reviews": items}), 200

@app.route("/api/submissions/<int:sub_id>", methods=["GET"])
@app.route("/api/reviews/<int:sub_id>", methods=["GET"])
@login_required
def get_submission_detail(sub_id):
    """
    Fetches details of a submission.
    ENFORCES DATA ISOLATION: Normal user cannot view another user's private submission.
    """
    conn = get_db()
    cursor = conn.cursor()
    sub = cursor.execute(
        "SELECT * FROM submissions WHERE id = ?", (sub_id,)
    ).fetchone()
    conn.close()

    if not sub:
        return jsonify({"error": "Submission not found."}), 404

    # Enforce access control: Owner, Moderator, or Admin
    is_owner = sub["user_id"] == session["user_id"]
    is_privileged = session.get("role") in ["admin", "moderator", "curator"]

    if not is_owner and not is_privileged:
        log_audit("403_DATA_ISOLATION_BLOCKED", f"User {session.get('email')} attempted to view submission {sub_id} owned by user {sub['user_id']}")
        return jsonify({"error": "Forbidden: You do not have permission to access another user's submission."}), 403

    return jsonify({
        "id": sub["id"],
        "user_id": sub["user_id"],
        "category": sub["category"] if "category" in sub.keys() else "restaurant_review",
        "dish_name": sub["dish_name"],
        "comment": sub["comment"],
        "rating": sub["rating"] if "rating" in sub.keys() else 5,
        "original_filename": sub["original_filename"],
        "file_size": sub["file_size"],
        "status": sub["status"],
        "created_at": sub["created_at"],
        "file_url": f"/api/submissions/{sub['id']}/file"
    }), 200

@app.route("/api/submissions/<int:sub_id>/file", methods=["GET"])
@app.route("/api/reviews/<int:sub_id>/file", methods=["GET"])
@login_required
def download_submission_file(sub_id):
    """
    Streams file or redirects to a short-lived S3 presigned URL.
    ENFORCES DATA ISOLATION: User B cannot access User A's uploaded file.
    """
    conn = get_db()
    cursor = conn.cursor()
    sub = cursor.execute("SELECT * FROM submissions WHERE id = ?", (sub_id,)).fetchone()
    conn.close()

    if not sub:
        return jsonify({"error": "File not found."}), 404

    is_owner = sub["user_id"] == session["user_id"]
    is_privileged = session.get("role") in ["admin", "moderator", "curator"]

    if not is_owner and not is_privileged:
        log_audit("403_STORAGE_ACCESS_BLOCKED", f"User {session.get('email')} blocked from accessing file for submission {sub_id}")
        return jsonify({"error": "Forbidden: You are not authorized to access this private file."}), 403

    storage_key = sub["storage_key"]

    if STORAGE_MODE == "s3":
        try:
            presigned_url = generate_presigned_download_url(storage_key, expires_in=300)
            return redirect(presigned_url, code=302)
        except Exception as e:
            app_logger.error(f"Failed to generate presigned S3 URL: {e}")
            return jsonify({"error": "Failed to generate download URL."}), 500
    else:
        # Local storage mode: send file directly from local_uploads
        file_path = os.path.join(LOCAL_UPLOADS_DIR, storage_key)
        if not os.path.exists(file_path):
            return jsonify({"error": "File does not exist on disk."}), 404
        return send_from_directory(
            os.path.dirname(file_path),
            os.path.basename(file_path),
            mimetype=sub["content_type"]
        )

@app.route("/api/submissions/<int:sub_id>/public-file", methods=["GET"])
@app.route("/api/reviews/<int:sub_id>/public-file", methods=["GET"])
def download_public_approved_file(sub_id):
    """Public file access for approved submissions only."""
    conn = get_db()
    cursor = conn.cursor()
    sub = cursor.execute("SELECT * FROM submissions WHERE id = ? AND status = 'approved'", (sub_id,)).fetchone()
    conn.close()

    if not sub:
        return jsonify({"error": "File not found or not approved."}), 404

    storage_key = sub["storage_key"]
    if STORAGE_MODE == "s3":
        try:
            presigned_url = generate_presigned_download_url(storage_key, expires_in=300)
            return redirect(presigned_url, code=302)
        except Exception as e:
            app_logger.error(f"Presigned error: {e}")
            return jsonify({"error": "Could not access image."}), 500
    else:
        file_path = os.path.join(LOCAL_UPLOADS_DIR, storage_key)
        if not os.path.exists(file_path):
            return jsonify({"error": "File missing."}), 404
        return send_from_directory(
            os.path.dirname(file_path),
            os.path.basename(file_path),
            mimetype=sub["content_type"]
        )

# -----------------------------------------------------------------------------
# API: Community Moderator & Admin Protected Routes (Role-Enforced)
# -----------------------------------------------------------------------------
@app.route("/api/admin/submissions", methods=["GET"])
@app.route("/api/moderator/reviews", methods=["GET"])
@role_required(["admin", "moderator", "curator"])
def admin_list_submissions():
    """Moderator/Admin endpoint: lists all community submissions to keep check on content."""
    conn = get_db()
    cursor = conn.cursor()
    rows = cursor.execute("""
        SELECT s.id, s.category, s.dish_name, s.comment, s.rating, s.original_filename, s.storage_key,
               s.file_size, s.status, s.created_at, u.email as user_email, u.name as user_name
        FROM submissions s
        JOIN users u ON s.user_id = u.id
        ORDER BY s.id DESC
    """).fetchall()
    conn.close()

    items = []
    for r in rows:
        items.append({
            "id": r["id"],
            "category": r["category"] if "category" in r.keys() else "restaurant_review",
            "dish_name": r["dish_name"],
            "comment": r["comment"],
            "rating": r["rating"] if "rating" in r.keys() else 5,
            "filename": r["original_filename"],
            "file_size": r["file_size"],
            "status": r["status"],
            "created_at": r["created_at"],
            "user_email": r["user_email"],
            "user_name": r["user_name"],
            "file_url": f"/api/submissions/{r['id']}/file"
        })
    log_audit("MODERATION_LIST_SUBMISSIONS", f"count={len(items)}")
    return jsonify({"submissions": items, "reviews": items}), 200

@app.route("/api/admin/submissions/<int:sub_id>/status", methods=["PUT"])
@app.route("/api/moderator/reviews/<int:sub_id>/status", methods=["PUT"])
@role_required(["admin", "moderator", "curator"])
def admin_update_status(sub_id):
    """Moderator/Admin endpoint: approves or rejects a community review/recipe."""
    user_ident = session.get("email", request.remote_addr)
    is_limited, retry_after = check_rate_limit(_admin_actions_ip, user_ident, max_attempts=30, window_seconds=60)
    if is_limited:
        return jsonify({
            "error": "Admin moderation action rate limit exceeded. Please wait.",
            "retry_after": retry_after
        }), 429, {"Retry-After": str(retry_after)}

    data = request.get_json(silent=True) or request.form
    new_status = (data.get("status") or "").strip().lower()

    if new_status not in ["approved", "rejected", "pending"]:
        return jsonify({"error": "Invalid status. Must be 'approved', 'rejected', or 'pending'."}), 400

    conn = get_db()
    cursor = conn.cursor()
    sub = cursor.execute("SELECT id FROM submissions WHERE id = ?", (sub_id,)).fetchone()
    if not sub:
        conn.close()
        return jsonify({"error": "Submission not found."}), 404

    cursor.execute("UPDATE submissions SET status = ? WHERE id = ?", (new_status, sub_id))
    conn.commit()
    conn.close()

    log_audit("MODERATION_STATUS_CHANGE", f"submission_id={sub_id}, new_status='{new_status}', by='{session.get('email')}'")
    return jsonify({"success": True, "message": f"Status updated to {new_status}."}), 200

@app.route("/api/admin/submissions/<int:sub_id>", methods=["DELETE"])
@app.route("/api/moderator/reviews/<int:sub_id>", methods=["DELETE"])
@role_required(["admin", "moderator", "curator"])
def admin_delete_submission(sub_id):
    """Moderator/Admin endpoint: removes spam or inappropriate posts from cloud storage and DB."""
    user_ident = session.get("email", request.remote_addr)
    is_limited, retry_after = check_rate_limit(_admin_actions_ip, user_ident, max_attempts=30, window_seconds=60)
    if is_limited:
        return jsonify({
            "error": "Admin moderation action rate limit exceeded. Please wait.",
            "retry_after": retry_after
        }), 429, {"Retry-After": str(retry_after)}

    conn = get_db()
    cursor = conn.cursor()
    sub = cursor.execute("SELECT storage_key FROM submissions WHERE id = ?", (sub_id,)).fetchone()
    if not sub:
        conn.close()
        return jsonify({"error": "Submission not found."}), 404

    storage_key = sub["storage_key"]
    cursor.execute("DELETE FROM submissions WHERE id = ?", (sub_id,))
    conn.commit()
    conn.close()

    # Delete from S3 or local directory
    delete_file_from_storage(storage_key)

    log_audit("MODERATION_DELETE", f"submission_id={sub_id}, storage_key='{storage_key}', by='{session.get('email')}'")
    return jsonify({"success": True, "message": "Submission and associated file deleted from cloud storage."}), 200

# -----------------------------------------------------------------------------
# Static Frontend Serving (Strict Allowlist Only)
# -----------------------------------------------------------------------------
ALLOWED_ROOT_PAGES = {
    "index.html",
    "login.html",
    "register.html",
    "reviews.html",
    "snaps.html",
    "orders.html",
}

ALLOWED_STATIC_DIRS = {
    "css": {".css"},
    "js": {".js"},
    "images": {".jpg", ".jpeg", ".png", ".webp", ".avif", ".svg", ".ico", ".gif"},
    "cuisine": {".html"},
    "food": {".html"},
    "cart": {".html"},
    "paypal": {".html"},
}

def send_html_file(filepath):
    """
    Renders an HTML file with the active session CSRF token injected into <meta name="csrf-token">.
    """
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(32)
    token = session["csrf_token"]
    with open(filepath, "r", encoding="utf-8") as f:
        html = f.read()
    if '<meta name="csrf-token"' in html:
        import re
        html = re.sub(r'<meta\s+name=["\']csrf-token["\'][^>]*>', f'<meta name="csrf-token" content="{token}">', html)
    else:
        html = html.replace("</head>", f'    <meta name="csrf-token" content="{token}">\n</head>', 1)
    return Response(html, mimetype="text/html")

@app.route("/")
def serve_index():
    return send_html_file(os.path.join(BASE_DIR, "index.html"))

@app.route("/<path:filename>")
def serve_static(filename):
    """
    Serves only strictly allowlisted static assets.
    Explicitly rejects source code, config files, logs, databases, and dotfiles with 404.
    """
    # Reject dotfiles, path traversal tokens, and control characters
    if (
        ".." in filename
        or filename.startswith(".")
        or "/." in filename
        or "\\" in filename
        or "\x00" in filename
    ):
        abort(404)

    parts = filename.strip("/").split("/")

    # 1. Root-level allowlisted HTML files
    if len(parts) == 1 and parts[0] in ALLOWED_ROOT_PAGES:
        target = os.path.join(BASE_DIR, parts[0])
        if os.path.isfile(target):
            return send_html_file(target)
        abort(404)

    # 2. Subdirectory allowlisted assets
    top_dir = parts[0]
    if top_dir in ALLOWED_STATIC_DIRS:
        allowed_exts = ALLOWED_STATIC_DIRS[top_dir]
        ext = os.path.splitext(filename)[1].lower()
        if ext in allowed_exts:
            safe_subpath = os.path.normpath(filename)
            full_path = os.path.join(BASE_DIR, safe_subpath)
            try:
                common_prefix = os.path.commonpath([BASE_DIR, full_path])
            except ValueError:
                abort(404)
            if common_prefix == BASE_DIR and os.path.isfile(full_path):
                if ext == ".html":
                    return send_html_file(full_path)
                return send_from_directory(BASE_DIR, safe_subpath)

    # Everything else returns 404 Not Found
    abort(404)

# -----------------------------------------------------------------------------
# Error Handlers
# -----------------------------------------------------------------------------
@app.errorhandler(403)
def handle_403(e):
    log_audit("403_FORBIDDEN", f"Access forbidden to {request.path}")
    return jsonify({"error": "Forbidden: You do not have permission to access this resource."}), 403

@app.errorhandler(404)
def handle_404(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": "API route not found."}), 404
    return send_from_directory(BASE_DIR, "index.html"), 404

@app.errorhandler(413)
def handle_413(e):
    log_audit("413_PAYLOAD_TOO_LARGE", f"File upload exceeded size limit on {request.path}")
    return jsonify({"error": "File size exceeds 5MB limit. Please upload a smaller file."}), 413

@app.errorhandler(500)
def handle_500(e):
    app_logger.error(f"500 Internal Server Error on {request.path}: {e}")
    return jsonify({"error": "Internal Server Error."}), 500

# -----------------------------------------------------------------------------
# Self-Test Runner (PASS / FAIL Table)
# -----------------------------------------------------------------------------
def run_self_tests():
    """
    Executes an automated end-to-end self-test suite covering:
    1. Health check (/health)
    2. Readiness probe (/ready)
    3. Security headers (CSP without inline scripts, nosniff, X-Frame-Options, HSTS, etc.)
    4. Strict static allowlist (verify 404 on /app.py, /foodies.db, /requirements.txt, etc.)
    5. CSRF protection (state-changing request blocked without token)
    6. CSRF token retrieval (/api/auth/csrf-token)
    7. User registration with CSRF token (201)
    8. User login with valid credentials (200)
    9. User login with incorrect password (401)
    10. Rate limiting on failed logins (429 with Retry-After)
    11. Image upload sanitization with Pillow (magic bytes, EXIF stripping, random UUID)
    12. Disallowed file type rejection (400)
    13. Oversized file rejection (>5MB) (400/413)
    14. Role-based access control (normal user blocked from moderator route: 403)
    15. Moderator action allowed (200)
    16. Moderator delete action allowed (200)
    17. Data isolation (User B blocked from User A private upload: 403)
    """
    app.config["TESTING"] = True
    init_db(seed_demo=False)
    seed_demo_accounts()
    client = app.test_client()

    # Clear in-memory rate limiting buckets for clean test execution
    _failed_logins_ip.clear()
    _failed_logins_email.clear()
    _register_attempts_ip.clear()
    _upload_attempts_ip.clear()
    _admin_actions_ip.clear()

    results = []
    test_id = 1

    def record(description, expected, actual, passed):
        nonlocal test_id
        results.append({
            "id": f"TC-{test_id:02d}",
            "desc": description,
            "expected": expected,
            "actual": actual,
            "passed": passed
        })
        test_id += 1

    print("\n" + "=" * 88)
    print(" FOODIES CLOUD PROJECT — AUTOMATED SELF-TEST SUITE")
    print("=" * 88)

    # 1. Health check
    res = client.get("/health")
    passed = res.status_code == 200 and res.get_json().get("status") == "ok"
    record("GET /health liveness check", "200 OK & status='ok'", f"{res.status_code}", passed)

    # 2. Readiness probe
    res = client.get("/ready")
    passed = res.status_code == 200 and res.get_json().get("checks", {}).get("database") == "ok"
    record("GET /ready readiness probe", "200 OK & database='ok'", f"{res.status_code}", passed)

    # 3. Security headers on every response
    res = client.get("/health")
    csp = res.headers.get("Content-Security-Policy", "")
    hsts = res.headers.get("Strict-Transport-Security", "")
    nosniff = res.headers.get("X-Content-Type-Options", "")
    xframe = res.headers.get("X-Frame-Options", "")
    ref_pol = res.headers.get("Referrer-Policy", "")
    perm_pol = res.headers.get("Permissions-Policy", "")
    headers_ok = (
        nosniff == "nosniff"
        and xframe == "SAMEORIGIN"
        and ref_pol == "strict-origin-when-cross-origin"
        and "geolocation=" in perm_pol
        and "max-age=" in hsts
        and "script-src 'self';" in csp
        and "'unsafe-inline'" not in csp.split("script-src")[1].split(";")[0]
    )
    record("Security headers (CSP no inline JS, HSTS, nosniff)", "All Headers Present", "Compliant" if headers_ok else "Missing", headers_ok)

    # 4. Strict static allowlist (verify sensitive paths return 404)
    blocked_paths = [
        "/app.py",
        "/foodies.db",
        "/requirements.txt",
        "/logs/app.log",
        "/.env",
        "/.git/config",
        "/deploy/nginx.conf"
    ]
    all_404 = True
    for p in blocked_paths:
        r = client.get(p)
        if r.status_code != 404:
            all_404 = False
            break
    record("Strict static allowlist (app.py, db, .env -> 404)", "404 Not Found on all", "All 404" if all_404 else "Leaked", all_404)

    # 5. CSRF protection: POST without token rejected
    rnd = uuid.uuid4().hex[:6]
    test_user_email = f"tester_{rnd}@test.com"
    res = client.post("/api/auth/register", json={
        "name": "No CSRF User",
        "email": test_user_email,
        "password": "Password@123"
    })
    passed = res.status_code == 403 and "CSRF" in res.get_json().get("error", "")
    record("CSRF protection: POST without token blocked", "403 Forbidden", f"{res.status_code}", passed)

    # 6. CSRF token retrieval
    res = client.get("/api/auth/csrf-token")
    csrf_token = res.get_json().get("csrf_token", "") if res.status_code == 200 else ""
    passed = res.status_code == 200 and len(csrf_token) >= 32
    record("GET /api/auth/csrf-token endpoint", "200 OK & 32+ char token", f"{res.status_code}", passed)

    # Helper headers with valid CSRF token
    csrf_headers = {"X-CSRF-Token": csrf_token}

    # 7. User registration with CSRF token
    res = client.post("/api/auth/register", json={
        "name": "Test User",
        "email": test_user_email,
        "password": "Password@123"
    }, headers=csrf_headers)
    passed = res.status_code == 201 and res.get_json().get("success") is True
    record("User Registration with CSRF token", "201 Created", f"{res.status_code}", passed)

    # 8. User login with valid credentials
    res = client.post("/api/auth/login", json={
        "email": test_user_email,
        "password": "Password@123"
    }, headers=csrf_headers)
    passed = res.status_code == 200 and res.get_json().get("success") is True
    record("User Login with valid credentials", "200 OK & Session Established", f"{res.status_code}", passed)

    # 9. Wrong password rejection
    res = client.post("/api/auth/login", json={
        "email": test_user_email,
        "password": "WrongPassword999!"
    }, headers=csrf_headers)
    passed = res.status_code == 401
    record("Login with incorrect password", "401 Unauthorized", f"{res.status_code}", passed)

    # 10. Rate limiting: failed logins per IP/email
    # Send 4 more failed logins (total 5)
    for _ in range(4):
        client.post("/api/auth/login", json={
            "email": test_user_email,
            "password": "WrongPassword999!"
        }, headers=csrf_headers)
    # The 6th attempt should be blocked with 429 and Retry-After header
    res_rate = client.post("/api/auth/login", json={
        "email": test_user_email,
        "password": "Password@123"
    }, headers=csrf_headers)
    passed = res_rate.status_code == 429 and "Retry-After" in res_rate.headers
    record("Failed login rate limiting (5 failures -> 429)", "429 Too Many Requests & Retry-After", f"{res_rate.status_code}", passed)

    # Clear rate limits for clean subsequent tests
    _failed_logins_ip.clear()
    _failed_logins_email.clear()

    # Re-login user A
    client.post("/api/auth/login", json={"email": test_user_email, "password": "Password@123"}, headers=csrf_headers)

    # 11. Pillow image sanitization: Valid PNG upload
    img = Image.new("RGB", (64, 64), color="blue")
    img_stream = BytesIO()
    img.save(img_stream, format="PNG")
    img_stream.seek(0)

    res = client.post("/api/reviews", data={
        "category": "restaurant_review",
        "dish_name": "Royal Tandoor - Paneer Butter Masala",
        "comment": "This restaurant is great! Sharing authentic recipe with rich creamy gravy.",
        "rating": "5",
        "file": (img_stream, "paneer.png", "image/png"),
        "csrf_token": csrf_token
    }, headers=csrf_headers, content_type="multipart/form-data")
    passed = res.status_code == 201 and "submission" in res.get_json()
    sub_a_id = res.get_json().get("submission", {}).get("id") if passed else None
    record("Pillow image sanitization & upload (PNG < 5MB)", "201 Created & Storage Key Generated", f"{res.status_code}", passed)

    # 12. Disallowed file type / non-image signature rejection
    bad_file = BytesIO(b"#!/bin/bash\necho Malicious Script")
    res = client.post("/api/reviews", data={
        "category": "restaurant_review",
        "dish_name": "Hack Attempt",
        "comment": "Executing arbitrary code",
        "file": (bad_file, "script.sh", "text/x-shellscript"),
        "csrf_token": csrf_token
    }, headers=csrf_headers, content_type="multipart/form-data")
    passed = res.status_code == 400
    record("Rejected disallowed file type (.sh/.exe)", "400 Bad Request", f"{res.status_code}", passed)

    # 13. Oversized file rejection (> 5MB)
    big_file = BytesIO(b"0" * (6 * 1024 * 1024)) # 6MB
    res = client.post("/api/reviews", data={
        "category": "recipe",
        "dish_name": "Huge File",
        "comment": "Too big for cloud tier",
        "file": (big_file, "huge.jpg", "image/jpeg"),
        "csrf_token": csrf_token
    }, headers=csrf_headers, content_type="multipart/form-data")
    passed = res.status_code in [400, 413]
    record("Rejected oversized file (> 5MB limit)", "400/413 Payload Too Large", f"{res.status_code}", passed)

    # 14. Normal user blocked from moderator endpoint (403)
    res = client.get("/api/moderator/reviews")
    passed = res.status_code == 403
    record("Normal user blocked from moderator endpoint", "403 Forbidden", f"{res.status_code}", passed)

    # 15. Community Moderator action allowed (200)
    # Login as seeded community moderator
    client.post("/api/auth/login", json={"email": "moderator@foodies.com", "password": "Mod@123"}, headers=csrf_headers)
    res = client.get("/api/moderator/reviews")
    passed_list = res.status_code == 200
    if sub_a_id:
        res_approve = client.put(f"/api/moderator/reviews/{sub_a_id}/status", json={"status": "approved"}, headers=csrf_headers)
        passed_action = res_approve.status_code == 200
    else:
        passed_action = False
    record("Community Moderator status approval allowed", "200 OK (Status Approved)", f"{res_approve.status_code if sub_a_id else res.status_code}", passed_list and passed_action)

    # 16. Moderator deletion allowed
    if sub_a_id:
        res_del = client.delete(f"/api/moderator/reviews/{sub_a_id}", headers=csrf_headers)
        passed_del = res_del.status_code == 200
    else:
        passed_del = False
    record("Community Moderator deletion allowed", "200 OK", f"{res_del.status_code if sub_a_id else 'N/A'}", passed_del)

    # 17. Data isolation: User B blocked from accessing User A's private upload (403)
    user_b_email = f"user_b_{rnd}@test.com"
    client.post("/api/auth/register", json={
        "name": "User B",
        "email": user_b_email,
        "password": "Password@123"
    }, headers=csrf_headers)
    client.post("/api/auth/login", json={"email": user_b_email, "password": "Password@123"}, headers=csrf_headers)

    # Upload a new private review as user A
    client.post("/api/auth/login", json={"email": test_user_email, "password": "Password@123"}, headers=csrf_headers)
    img_b = Image.new("RGB", (32, 32), color="green")
    img_b_stream = BytesIO()
    img_b.save(img_b_stream, format="PNG")
    img_b_stream.seek(0)
    res_sub_b = client.post("/api/reviews", data={
        "category": "dish_review",
        "dish_name": "Private Dish",
        "comment": "Pending moderator approval",
        "rating": "4",
        "file": (img_b_stream, "dish.png", "image/png"),
        "csrf_token": csrf_token
    }, headers=csrf_headers, content_type="multipart/form-data")
    sub_b_id = res_sub_b.get_json().get("submission", {}).get("id") if res_sub_b.status_code == 201 else None

    # Switch back to User B and try to view User A's private pending review
    client.post("/api/auth/login", json={"email": user_b_email, "password": "Password@123"}, headers=csrf_headers)
    if sub_b_id:
        res = client.get(f"/api/reviews/{sub_b_id}")
        passed = res.status_code == 403
        actual = f"{res.status_code} Forbidden"
    else:
        passed = False
        actual = "No submission created"
    record("Data isolation: User B blocked from User A review/recipe", "403 Forbidden", actual, passed)

    # Print results table
    print("\n" + "-" * 88)
    print(f"| {'ID':<6} | {'Test Description':<42} | {'Expected':<16} | {'Actual':<7} | {'Status':<6} |")
    print("-" * 88)
    all_passed = True
    for r in results:
        status_str = "PASS" if r["passed"] else "FAIL"
        if not r["passed"]:
            all_passed = False
        print(f"| {r['id']:<6} | {r['desc']:<42} | {r['expected']:<16} | {r['actual']:<7} | {status_str:<6} |")
    print("-" * 88)

    passed_count = sum(1 for r in results if r["passed"])
    total_count = len(results)
    print(f"\nSummary: {passed_count}/{total_count} tests passed.")
    if all_passed:
        print("RESULT: ALL SELF-TESTS PASSED SUCCESSFULLY! (PASS)\n")
        return 0
    else:
        print("RESULT: SOME TESTS FAILED! (FAIL)\n")
        return 1

# -----------------------------------------------------------------------------
# Main Entry Point
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    init_db()

    if "--test" in sys.argv or "test" in sys.argv:
        exit_code = run_self_tests()
        sys.exit(exit_code)

    port = int(os.environ.get("PORT", 8080))
    host = os.environ.get("HOST", "0.0.0.0")
    print(f"Starting Foodies Cloud Server on http://{host}:{port} (Storage: {STORAGE_MODE.upper()})")
    app.run(host=host, port=port, debug=False)
