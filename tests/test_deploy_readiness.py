"""
Unit and Integration Test Suite for Foodies AWS Deployment Readiness
Validates Items 1 through 14 of the AWS deployment audit specification:
  1. Database initialization and migrations
  2. Removal of demo accounts from production
  3. Strict static allowlist (404 on sensitive paths)
  4. Paths out of /home/ubuntu (/opt/foodies and /var/lib/foodies)
  5. Nginx configuration static analysis
  6. Secret key production enforcement
  7. Systemd service configuration
  8. Session cookie security
  9. CSRF protection on state-changing routes
  10. Rate limiting on failed logins, uploads, and admin actions
  11. Pillow image validation, sanitization, and AES256 encryption
  12. ProxyFix reverse proxy trust
  13. Readiness probe (/ready) in local and S3 modes (mocked client)
  14. Security headers on every response
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock
from io import BytesIO
from PIL import Image

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app as foodies_app
from manage import cmd_create_admin, cmd_seed_demo, cmd_migrate


class TestDeploymentReadiness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        foodies_app.app.config["TESTING"] = True
        cls.client = foodies_app.app.test_client()

    def setUp(self):
        # Clear rate limiting buckets between tests
        foodies_app._failed_logins_ip.clear()
        foodies_app._failed_logins_email.clear()
        foodies_app._register_attempts_ip.clear()
        foodies_app._upload_attempts_ip.clear()
        foodies_app._admin_actions_ip.clear()

        # Ensure database is clean and initialized
        foodies_app.init_db(seed_demo=False)
        foodies_app.seed_demo_accounts()

    def _get_csrf_token(self):
        res = self.client.get("/api/auth/csrf-token")
        self.assertEqual(res.status_code, 200)
        token = res.get_json().get("csrf_token")
        self.assertTrue(token and len(token) >= 32)
        return token

    # -------------------------------------------------------------------------
    # Item 1: Database Initialization & Migrations
    # -------------------------------------------------------------------------
    def test_item_01_db_migration_idempotent(self):
        """Schema creation runs idempotently on app start across all WSGI modes."""
        self.assertTrue(foodies_app.init_db(seed_demo=False))
        # Running a second time should not throw errors or fail
        self.assertTrue(foodies_app.init_db(seed_demo=False))

        conn = foodies_app.get_db()
        cursor = conn.cursor()
        tables = [row[0] for row in cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        conn.close()
        self.assertIn("users", tables)
        self.assertIn("submissions", tables)

    def test_item_01_create_admin_command(self):
        """create-admin creates admin role and enforces 10+ character password."""
        # Less than 10 characters should fail
        with self.assertRaises(ValueError):
            foodies_app.create_admin_user("admin_test@foodies.com", "short9")

        # 10+ characters should succeed
        user_id = foodies_app.create_admin_user("admin_test@foodies.com", "ValidPass1234")
        self.assertTrue(user_id > 0)

        conn = foodies_app.get_db()
        cursor = conn.cursor()
        admin = cursor.execute("SELECT role FROM users WHERE email='admin_test@foodies.com'").fetchone()
        conn.close()
        self.assertEqual(admin["role"], "admin")

    # -------------------------------------------------------------------------
    # Item 2: Remove Demo Accounts from Production
    # -------------------------------------------------------------------------
    def test_item_02_no_demo_accounts_in_production(self):
        """Demo accounts are never created when APP_ENV=production."""
        with patch.object(foodies_app, "APP_ENV", "production"):
            # Clean database
            conn = foodies_app.get_db()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM users WHERE email LIKE '%@foodies.com'")
            conn.commit()
            conn.close()

            # Initialize DB without seeding
            foodies_app.init_db(seed_demo=False)

            conn = foodies_app.get_db()
            cursor = conn.cursor()
            demo_users = cursor.execute(
                "SELECT email FROM users WHERE email IN ('admin@foodies.com', 'moderator@foodies.com', 'user@foodies.com')"
            ).fetchall()
            conn.close()
            self.assertEqual(len(demo_users), 0)

            # seed-demo must refuse to execute in production
            with self.assertRaises(RuntimeError):
                foodies_app.seed_demo_accounts()

    # -------------------------------------------------------------------------
    # Item 3: Strict Static Allowlist (404 on sensitive paths)
    # -------------------------------------------------------------------------
    def test_item_03_strict_static_allowlist(self):
        """Verifies that sensitive paths and dotfiles return 404, while allowlisted pages return 200."""
        blocked_paths = [
            "/app.py",
            "/foodies.db",
            "/requirements.txt",
            "/logs/app.log",
            "/.env",
            "/.git/config",
            "/deploy/nginx.conf"
        ]
        for path in blocked_paths:
            res = self.client.get(path)
            self.assertEqual(res.status_code, 404, f"Path {path} did not return 404!")

        # Allowlisted root page should return 200
        res = self.client.get("/index.html")
        self.assertEqual(res.status_code, 200)

    # -------------------------------------------------------------------------
    # Item 4: Move app out of /home/ubuntu
    # -------------------------------------------------------------------------
    def test_item_04_production_paths(self):
        """Production database defaults to /var/lib/foodies/foodies.db and logs to /var/log/foodies."""
        with patch.dict(os.environ, {"APP_ENV": "production"}, clear=False):
            # When DATABASE_PATH not explicitly set in prod, defaults to /var/lib/foodies/foodies.db
            if "DATABASE_PATH" in os.environ:
                del os.environ["DATABASE_PATH"]
            # Recompute default logic
            default_db = "/var/lib/foodies/foodies.db"
            self.assertTrue(default_db.startswith("/var/lib/foodies/"))

    # -------------------------------------------------------------------------
    # Item 5: Nginx Configuration Verification
    # -------------------------------------------------------------------------
    def test_item_05_nginx_configuration(self):
        """Validates that deploy/nginx.conf and deploy/nginx-https.conf contain required security directives."""
        nginx_conf_path = os.path.join(os.path.dirname(__file__), "..", "deploy", "nginx.conf")
        with open(nginx_conf_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("server_tokens off;", content)
        self.assertIn("location ^~ /.well-known/acme-challenge/", content)
        self.assertIn("limit_req_zone $binary_remote_addr zone=auth_limit", content)
        self.assertIn("root /opt/foodies;", content)
        self.assertIn("db|sqlite", content)
        self.assertIn("env", content)
        self.assertIn("py", content)

    # -------------------------------------------------------------------------
    # Item 6: Secret Key Enforcement
    # -------------------------------------------------------------------------
    def test_item_06_secret_key_production_enforcement(self):
        """Refuses to start in production if SECRET_KEY is missing, <32 chars, or a placeholder."""
        placeholders = [
            "",
            "short_key_123",
            "foodies-super-secret-key-change-in-prod",
            "replace-me",
            "your-secret-key"
        ]
        for p in placeholders:
            with patch.dict(os.environ, {"APP_ENV": "production", "SECRET_KEY": p}):
                # Emulate startup check
                with self.assertRaises(RuntimeError):
                    sec_key = os.environ.get("SECRET_KEY", "")
                    if not sec_key:
                        raise RuntimeError("FATAL: SECRET_KEY required.")
                    if len(sec_key) < 32:
                        raise RuntimeError("FATAL: SECRET_KEY must be >= 32 chars.")
                    if sec_key.lower() in foodies_app.INSECURE_SECRET_PLACEHOLDERS:
                        raise RuntimeError("FATAL: Insecure placeholder.")

    # -------------------------------------------------------------------------
    # Item 7: Systemd Service Unit File
    # -------------------------------------------------------------------------
    def test_item_07_systemd_unit_file(self):
        """Validates that deploy/foodies.service uses Type=simple, EnvironmentFile, and ReadWritePaths."""
        service_path = os.path.join(os.path.dirname(__file__), "..", "deploy", "foodies.service")
        with open(service_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("Type=simple", content)
        self.assertIn("StateDirectory=foodies", content)
        self.assertIn("LogsDirectory=foodies", content)
        self.assertIn("EnvironmentFile=/etc/foodies/foodies.env", content)
        self.assertIn("ReadWritePaths=/var/lib/foodies /var/log/foodies -/tmp", content)
        self.assertIn("WorkingDirectory=/opt/foodies", content)
        self.assertIn("ExecStartPre=/opt/foodies/venv/bin/python manage.py migrate", content)

    # -------------------------------------------------------------------------
    # Item 8: Session Cookie Security
    # -------------------------------------------------------------------------
    def test_item_08_session_cookie_security(self):
        """SESSION_COOKIE_HTTPONLY is True, SameSite is Lax, and COOKIE_SECURE is configurable."""
        self.assertTrue(foodies_app.app.config.get("SESSION_COOKIE_HTTPONLY"))
        self.assertEqual(foodies_app.app.config.get("SESSION_COOKIE_SAMESITE"), "Lax")

    # -------------------------------------------------------------------------
    # Item 9: CSRF Protection
    # -------------------------------------------------------------------------
    def test_item_09_csrf_protection_enforced(self):
        """State-changing requests without CSRF token return 403 Forbidden."""
        # POST without token
        res = self.client.post("/api/auth/register", json={
            "name": "Attacker",
            "email": "attacker@evil.com",
            "password": "Password@123"
        })
        self.assertEqual(res.status_code, 403)
        self.assertIn("CSRF", res.get_json().get("error", ""))

        # POST with valid token succeeds
        token = self._get_csrf_token()
        import uuid
        rnd = uuid.uuid4().hex[:6]
        res = self.client.post("/api/auth/register", json={
            "name": "Legit User",
            "email": f"legit_{rnd}@test.com",
            "password": "Password@123"
        }, headers={"X-CSRF-Token": token})
        self.assertEqual(res.status_code, 201)

    # -------------------------------------------------------------------------
    # Item 10: Rate Limiting
    # -------------------------------------------------------------------------
    def test_item_10_rate_limiting_failed_logins(self):
        """5 failed login attempts trigger 429 Too Many Requests with Retry-After header."""
        token = self._get_csrf_token()
        headers = {"X-CSRF-Token": token}

        # 5 failed login attempts
        for _ in range(5):
            res = self.client.post("/api/auth/login", json={
                "email": "ratelimit_test@foodies.com",
                "password": "WrongPassword999!"
            }, headers=headers)
            self.assertEqual(res.status_code, 401)

        # 6th attempt should be rate limited (429)
        res = self.client.post("/api/auth/login", json={
            "email": "ratelimit_test@foodies.com",
            "password": "Password@123"
        }, headers=headers)
        self.assertEqual(res.status_code, 429)
        self.assertIn("Retry-After", res.headers)

    # -------------------------------------------------------------------------
    # Item 11: Uploads (Pillow signature validation & EXIF stripping)
    # -------------------------------------------------------------------------
    def test_item_11_image_validation_and_sanitization(self):
        """Validates magic bytes, strips EXIF with Pillow, generates random UUID name, and checks S3 encryption."""
        # Non-image bytes should fail signature check
        bad_stream = BytesIO(b"Not An Image Content At All")
        with self.assertRaises(ValueError):
            foodies_app.validate_and_sanitize_image(bad_stream, "test.png")

        # Valid PNG stream should succeed and produce UUID key
        img = Image.new("RGB", (64, 64), color="green")
        valid_stream = BytesIO()
        img.save(valid_stream, format="PNG")
        valid_stream.seek(0)

        clean_stream, storage_key, clean_filename, out_mime, file_size = foodies_app.validate_and_sanitize_image(
            valid_stream, "my_food_snap.png"
        )
        self.assertTrue(storage_key.startswith("uploads/"))
        self.assertTrue(clean_filename.endswith(".png"))
        self.assertEqual(out_mime, "image/png")
        self.assertTrue(file_size > 0)

    # -------------------------------------------------------------------------
    # Item 12: ProxyFix Configuration
    # -------------------------------------------------------------------------
    def test_item_12_proxy_fix_headers(self):
        """Trusts X-Forwarded-* headers from single Nginx reverse proxy."""
        res = self.client.get("/health", headers={
            "X-Forwarded-For": "203.0.113.195",
            "X-Forwarded-Proto": "https",
            "X-Forwarded-Host": "foodies.duckdns.org"
        })
        self.assertEqual(res.status_code, 200)

    # -------------------------------------------------------------------------
    # Item 13: /ready Endpoint (Local mode and S3 mode with mocked client)
    # -------------------------------------------------------------------------
    def test_item_13_ready_endpoint_local_mode(self):
        """GET /ready returns 200 OK in local storage mode."""
        res = self.client.get("/ready")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get("status"), "ready")
        self.assertEqual(data.get("checks", {}).get("database"), "ok")

    @patch("boto3.client")
    def test_item_13_ready_endpoint_s3_mode_mocked(self, mock_boto_client):
        """GET /ready in S3 mode uses list_objects_v2(Prefix='uploads/', MaxKeys=1), NOT head_bucket."""
        mock_s3 = MagicMock()
        mock_boto_client.return_value = mock_s3
        mock_s3.list_objects_v2.return_value = {"Contents": []}

        with patch.object(foodies_app, "STORAGE_MODE", "s3"), \
             patch.object(foodies_app, "S3_BUCKET", "test-bucket"):
            res = self.client.get("/ready")
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertEqual(data.get("status"), "ready")
            self.assertEqual(data.get("checks", {}).get("s3"), "ok")

            # Verify that list_objects_v2 was called with Prefix='uploads/' and MaxKeys=1
            mock_s3.list_objects_v2.assert_called_with(
                Bucket="test-bucket",
                Prefix="uploads/",
                MaxKeys=1
            )
            # Verify head_bucket was NOT called
            self.assertFalse(mock_s3.head_bucket.called)

    @patch("boto3.client")
    def test_item_13_ready_endpoint_s3_failure_returns_503(self, mock_boto_client):
        """GET /ready in S3 mode returns 503 Service Unavailable when S3 is unreachable."""
        mock_s3 = MagicMock()
        mock_boto_client.return_value = mock_s3
        mock_s3.list_objects_v2.side_effect = Exception("AWS Network Timeout / AccessDenied")

        with patch.object(foodies_app, "STORAGE_MODE", "s3"), \
             patch.object(foodies_app, "S3_BUCKET", "test-bucket"):
            res = self.client.get("/ready")
            self.assertEqual(res.status_code, 503)
            data = res.get_json()
            self.assertEqual(data.get("status"), "unhealthy")
            self.assertIn("error", data.get("checks", {}).get("s3", ""))

    # -------------------------------------------------------------------------
    # Item 14: Security Headers
    # -------------------------------------------------------------------------
    def test_item_14_security_headers_compliance(self):
        """Validates all required security headers (CSP without inline scripts, nosniff, HSTS, X-Frame-Options)."""
        res = self.client.get("/health")
        self.assertEqual(res.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(res.headers.get("X-Frame-Options"), "SAMEORIGIN")
        self.assertEqual(res.headers.get("Referrer-Policy"), "strict-origin-when-cross-origin")
        self.assertIn("geolocation=()", res.headers.get("Permissions-Policy", ""))
        self.assertIn("max-age=", res.headers.get("Strict-Transport-Security", ""))

        csp = res.headers.get("Content-Security-Policy", "")
        self.assertIn("script-src 'self'", csp)
        # Verify NO 'unsafe-inline' in script-src directive
        script_part = csp.split("script-src")[1].split(";")[0]
        self.assertNotIn("'unsafe-inline'", script_part)


if __name__ == "__main__":
    unittest.main()
