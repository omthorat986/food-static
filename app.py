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
    abort
)
import bcrypt
import boto3
from botocore.exceptions import ClientError
from werkzeug.utils import secure_filename

# -----------------------------------------------------------------------------
# Configuration
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
S3_BUCKET = os.environ.get("S3_BUCKET", "foodies-cloud-storage")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
SECRET_KEY = os.environ.get("SECRET_KEY", "foodies-insecure-dev-key-change-in-prod")
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
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("COOKIE_SECURE", "false").lower() == "true"

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

def seed_demo_accounts(conn=None):
    """
    Seeds default demo accounts for local development and self-testing.
    CRITICAL: Never seeds demo accounts when APP_ENV == 'production'.
    """
    if APP_ENV == "production":
        app_logger.warning("Refusing to seed demo accounts in production environment (APP_ENV=production).")
        return False

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
# API: Health & Status
# -----------------------------------------------------------------------------
@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint for AWS Route53/ELB/CloudWatch and frontend status badge."""
    return jsonify({
        "status": "ok",
        "service": "foodies-cloud",
        "storage_mode": STORAGE_MODE,
        "region": AWS_REGION if STORAGE_MODE == "s3" else "local",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }), 200

# -----------------------------------------------------------------------------
# API: Authentication Routes
# -----------------------------------------------------------------------------
@app.route("/api/auth/register", methods=["POST"])
def register():
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
    data = request.get_json(silent=True) or request.form
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not email or not password:
        return jsonify({"error": "Email and password are required."}), 400

    conn = get_db()
    cursor = conn.cursor()
    user = cursor.execute(
        "SELECT id, name, email, password_hash, role FROM users WHERE email = ?",
        (email,)
    ).fetchone()
    conn.close()

    if not user or not bcrypt.checkpw(password.encode("utf-8"), user["password_hash"].encode("utf-8")):
        log_audit("LOGIN_FAILED", f"email='{email}', reason='invalid_credentials'")
        return jsonify({"error": "Invalid email or password."}), 401

    # Valid login
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
    """
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
    mimetype = file.mimetype or "application/octet-stream"

    # Validate file type
    if not is_allowed_file(filename, mimetype):
        log_audit("UPLOAD_REJECTED", f"reason='disallowed_file_type', filename='{filename}', mime='{mimetype}'")
        return jsonify({
            "error": "Invalid file type. Only PNG, JPG, JPEG, and WEBP images are allowed."
        }), 400

    # Validate file size
    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)

    if file_size <= 0:
        return jsonify({"error": "Uploaded file is empty."}), 400
    if file_size > MAX_FILE_SIZE_BYTES:
        log_audit("UPLOAD_REJECTED", f"reason='oversized_file', size={file_size}")
        return jsonify({"error": "File size exceeds 5MB limit. Please upload a smaller image."}), 400

    # Generate unique storage key
    file_ext = filename.rsplit(".", 1)[-1].lower()
    storage_key = f"uploads/{uuid.uuid4().hex}_{filename}"

    # Store in S3 or local directory
    try:
        upload_file_to_storage(file, storage_key, mimetype)
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
# Static Frontend Serving (Unchanged existing files)
# -----------------------------------------------------------------------------
@app.route("/")
def serve_index():
    return send_from_directory(BASE_DIR, "index.html")

@app.route("/<path:filename>")
def serve_static(filename):
    """Serves existing static files unchanged."""
    target_path = os.path.join(BASE_DIR, filename)
    if os.path.isfile(target_path):
        return send_from_directory(BASE_DIR, filename)
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
    2. Register and login
    3. Wrong password rejection
    4. Valid file upload to storage
    5. Disallowed file type rejection (.sh/.exe)
    6. Oversized file rejection (>5MB)
    7. Normal user blocked from admin action (403)
    8. Admin action allowed (200)
    9. Data isolation: User B blocked from accessing User A's private upload (403)
    """
    init_db(seed_demo=False)
    seed_demo_accounts()
    client = app.test_client()

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

    print("\n" + "=" * 80)
    print(" FOODIES CLOUD PROJECT — AUTOMATED SELF-TEST SUITE")
    print("=" * 80)

    # 1. Health check
    res = client.get("/health")
    passed = res.status_code == 200 and res.get_json().get("status") == "ok"
    record("GET /health endpoint check", "200 OK & status='ok'", f"{res.status_code}", passed)

    # 2. User registration
    rnd = uuid.uuid4().hex[:6]
    test_user_email = f"tester_{rnd}@test.com"
    res = client.post("/api/auth/register", json={
        "name": "Test User",
        "email": test_user_email,
        "password": "Password@123"
    })
    passed = res.status_code == 201 and res.get_json().get("success") is True
    record("User Registration (/api/auth/register)", "201 Created", f"{res.status_code}", passed)

    # 3. User login (valid)
    res = client.post("/api/auth/login", json={
        "email": test_user_email,
        "password": "Password@123"
    })
    passed = res.status_code == 200 and res.get_json().get("success") is True
    record("User Login with valid credentials", "200 OK & Session Established", f"{res.status_code}", passed)

    # 4. Wrong password rejection
    res = client.post("/api/auth/login", json={
        "email": test_user_email,
        "password": "WrongPassword999!"
    })
    passed = res.status_code == 401
    record("Login with incorrect password", "401 Unauthorized", f"{res.status_code}", passed)

    # Re-login user A for subsequent tests
    client.post("/api/auth/login", json={"email": test_user_email, "password": "Password@123"})

    # 5. Valid file upload (Restaurant Review & Recipe Sharing)
    from io import BytesIO
    dummy_png = BytesIO(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")
    res = client.post("/api/reviews", data={
        "category": "restaurant_review",
        "dish_name": "Royal Tandoor - Paneer Butter Masala",
        "comment": "This restaurant is great! Sharing authentic recipe with rich creamy gravy.",
        "rating": "5",
        "file": (dummy_png, "paneer.png", "image/png")
    }, content_type="multipart/form-data")
    passed = res.status_code == 201 and "submission" in res.get_json()
    sub_a_id = res.get_json().get("submission", {}).get("id") if passed else None
    record("Valid review & recipe upload (PNG/JPG < 5MB)", "201 Created & Storage Key Generated", f"{res.status_code}", passed)

    # 6. Disallowed file type rejection
    bad_file = BytesIO(b"#!/bin/bash\necho Malicious Script")
    res = client.post("/api/reviews", data={
        "category": "restaurant_review",
        "dish_name": "Hack Attempt",
        "comment": "Executing arbitrary code",
        "file": (bad_file, "script.sh", "text/x-shellscript")
    }, content_type="multipart/form-data")
    passed = res.status_code == 400
    record("Rejected disallowed file type (.sh/.exe)", "400 Bad Request", f"{res.status_code}", passed)

    # 7. Oversized file rejection (> 5MB)
    big_file = BytesIO(b"0" * (6 * 1024 * 1024)) # 6MB
    res = client.post("/api/reviews", data={
        "category": "recipe",
        "dish_name": "Huge File",
        "comment": "Too big for cloud tier",
        "file": (big_file, "huge.jpg", "image/jpeg")
    }, content_type="multipart/form-data")
    passed = res.status_code in [400, 413]
    record("Rejected oversized file (> 5MB limit)", "400/413 Payload Too Large", f"{res.status_code}", passed)

    # 8. Normal user blocked from moderator action (403)
    res = client.get("/api/moderator/reviews")
    passed = res.status_code == 403
    record("Normal user blocked from moderator endpoint", "403 Forbidden", f"{res.status_code}", passed)

    # 9. Community Moderator action allowed (200)
    # Login as seeded community moderator
    client.post("/api/auth/login", json={"email": "moderator@foodies.com", "password": "Mod@123"})
    res = client.get("/api/moderator/reviews")
    passed_list = res.status_code == 200
    if sub_a_id:
        res_approve = client.put(f"/api/moderator/reviews/{sub_a_id}/status", json={"status": "approved"})
        passed_action = res_approve.status_code == 200
    else:
        passed_action = False
    record("Community Moderator action allowed", "200 OK (Status Approved)", f"{res_approve.status_code if sub_a_id else res.status_code}", passed_list and passed_action)

    # 10. Data isolation: User B blocked from accessing User A's private upload (403)
    user_b_email = f"user_b_{rnd}@test.com"
    client.post("/api/auth/register", json={
        "name": "User B",
        "email": user_b_email,
        "password": "Password@123"
    })
    client.post("/api/auth/login", json={"email": user_b_email, "password": "Password@123"})
    if sub_a_id:
        res = client.get(f"/api/reviews/{sub_a_id}")
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
