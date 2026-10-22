# Foodies Cloud Mini Project — Test Cases & Validation Matrix

This document records the comprehensive test suite and validation matrix for the **Foodies** cloud computing project, covering automated backend tests, security access controls, and live AWS cloud infrastructure checks.

---

## 1. Automated Backend & API Test Suite (Run via `python app.py --test`)

| ID | Test Case Description | Test Procedure | Expected Result | Actual Result | Status |
| :--- | :--- | :--- | :--- | :--- | :---: |
| **TC-01** | Health Check Endpoint | `GET /health` | HTTP 200 OK, JSON containing `{"status": "ok"}` | HTTP 200 OK, `{"status":"ok","storage_mode":"local"}` | **PASS** |
| **TC-02** | User Registration | `POST /api/auth/register` with new name, email, password | HTTP 201 Created, user account stored in SQLite, bcrypt hash generated | HTTP 201 Created, record created | **PASS** |
| **TC-03** | User Login (Valid Credentials) | `POST /api/auth/login` with registered email and password | HTTP 200 OK, HttpOnly session cookie established, user role returned | HTTP 200 OK, session cookie received | **PASS** |
| **TC-04** | User Login (Invalid Password) | `POST /api/auth/login` with invalid password | HTTP 401 Unauthorized, error message returned, audit failure logged | HTTP 401 Unauthorized, failure logged | **PASS** |
| **TC-05** | Valid Review & Recipe Upload | `POST /api/reviews` with review/recipe, rating, and image (< 5MB) | HTTP 201 Created, file saved with AES256 encryption, unique storage key generated | HTTP 201 Created, storage key assigned | **PASS** |
| **TC-06** | Disallowed File Type Rejection | `POST /api/reviews` with shell script (`script.sh`) | HTTP 400 Bad Request, file rejected, upload rejection logged | HTTP 400 Bad Request, upload blocked | **PASS** |
| **TC-07** | Oversized File Rejection | `POST /api/reviews` with 6 MB payload | HTTP 400 / 413 Payload Too Large, transaction aborted | HTTP 400 Payload Too Large | **PASS** |
| **TC-08** | Privilege Enforcement (User -> Moderator) | Normal authenticated user calls `GET /api/moderator/reviews` | HTTP 403 Forbidden, request rejected, security audit logged | HTTP 403 Forbidden, blocked server-side | **PASS** |
| **TC-09** | Community Moderator Action Execution | Logged-in moderator calls `PUT /api/moderator/reviews/<id>/status` | HTTP 200 OK, review/recipe status updated to approved | HTTP 200 OK, status updated | **PASS** |
| **TC-10** | Private Data Isolation | User B attempts to access User A's private review/recipe details | HTTP 403 Forbidden, cross-tenant data access blocked | HTTP 403 Forbidden, data isolated | **PASS** |

---

## 2. Cloud Infrastructure & Security Verification Suite (Live AWS Checks)

| ID | Test Case Description | Test Procedure | Expected Result | Actual Result | Status |
| :--- | :--- | :--- | :--- | :--- | :---: |
| **TC-11** | HTTP to HTTPS Automated Redirection | `curl -I http://<domain>/` | HTTP 301 Moved Permanently with `Location: https://<domain>/` | HTTP/1.1 301 Moved Permanently, Location header present | **PASS** |
| **TC-12** | Direct S3 Object Access Blocked | Direct browser request to `https://<bucket>.s3.amazonaws.com/uploads/<key>` | HTTP 403 AccessDenied XML returned by Amazon S3 | `<code>AccessDenied</code> Access Denied` HTTP 403 | **PASS** |
| **TC-13** | Security Group SSH Port Restriction | Port scan / SSH connection attempt from unauthorized IP address | Connection times out / dropped at AWS VPC perimeter | Packet dropped; connection timed out | **PASS** |
| **TC-14** | Presigned URL Expiration | Access generated S3 presigned URL after 305 seconds (> 300s expiry) | Amazon S3 returns HTTP 403 `Request has expired` | `<code>AccessDenied</code> Request has expired` | **PASS** |
| **TC-15** | CloudWatch Log Streaming | Execute actions in app and inspect CloudWatch log group `/aws/ec2/foodies/app` | Log stream contains real-time JSON/text audit entries with IP and timestamps | Log stream active and populated in CloudWatch | **PASS** |
| **TC-16** | CloudWatch High-CPU Alarm & SNS Alert | Run CPU stress test on EC2 (`stress-ng --cpu 2 --timeout 120s`) | CPU > 70% triggers alarm state; SNS dispatches alert email to student | Alarm state transitions to `ALARM`; SNS email delivered | **PASS** |

---

## 3. Summary of Test Execution
- Total Test Cases: 16
- Passed: 16
- Failed: 0
- Code Coverage: 100% of assignment requirements (Auth, Storage, IAM, RBAC, SSL, Health, Monitoring, Isolation).
