# System Architecture & Request Flow

This document details the cloud computing architecture, components, and security boundary for the **Foodies** cloud deployment.

---

## 1. Architectural Diagram (Mermaid)

```mermaid
flowchart TD
    %% External Clients & DNS
    subgraph Clients ["Public Internet & Clients"]
        UserBrowser["User Browser (Customer / Moderator / Admin)"]
        DuckDNS["DuckDNS Dynamic DNS Resolution"]
    end

    %% AWS Cloud Perimeter
    subgraph AWSCloud ["AWS Cloud Infrastructure (us-east-1)"]

        subgraph SecurityBoundary ["EC2 Virtual Machine Boundary (t3.micro / Ubuntu 24.04)"]
            SG["EC2 Security Group (foodies-web-sg)<br/>• Port 443 (HTTPS) - Anywhere<br/>• Port 80 (HTTP) - Anywhere (Redirect)<br/>• Port 22 (SSH) - Restricted to Admin IP"]

            subgraph ReverseProxy ["Nginx Web Server & Reverse Proxy"]
                NginxHTTP["Port 80 Listener<br/>(301 Redirect to HTTPS)"]
                NginxHTTPS["Port 443 Listener<br/>(SSL/TLS via Let's Encrypt)"]
                StaticCache["Static File Cache<br/>(HTML, CSS, JS, Images)"]
            end

            subgraph AppServer ["Application Layer (systemd managed)"]
                Gunicorn["Gunicorn WSGI (2 Workers, 2 Threads)"]
                FlaskBackend["Flask Application (app.py)<br/>• RBAC (User / Moderator / Admin)<br/>• Passwords via Bcrypt<br/>• Audit Logging<br/>• S3 Client (Boto3)"]
                SQLiteDB[("SQLite Database<br/>foodies.db<br/>(Users, Reviews, Recipes)")]
                LocalLog["Rotating Log File<br/>logs/app.log"]
            end

            CWAgent["CloudWatch Unified Agent<br/>(Collects System Metrics & Logs)"]
        end

        subgraph StorageLayer ["Object Storage Layer"]
            S3Bucket[("Amazon S3 Bucket<br/>foodies-cloud-storage<br/>• Block Public Access: ON<br/>• Server-Side Encryption: AES256<br/>• Prefix: /uploads/*")]
        end

        subgraph IAMLayer ["Identity & Access Management"]
            EC2Role["EC2 Instance Profile Role<br/>(FoodiesEC2Role)<br/>• Least Privilege Policy<br/>• Restricted to s3:Put/Get/Delete on uploads/*"]
        end

        subgraph MonitoringLayer ["CloudWatch & Notification Services"]
            CWLogs["CloudWatch Logs<br/>/aws/ec2/foodies/app<br/>/aws/ec2/foodies/nginx-access"]
            CWMetrics["CloudWatch Metrics<br/>CPU, Memory %, Disk %"]
            CWAlarm["CloudWatch Alarm<br/>(CPUUtilization > 70%)"]
            SNSTopic["Amazon SNS Topic<br/>(foodies-cpu-alarm)"]
            EmailAlert["Email Notification<br/>to Administrator"]
        end
    end

    %% Interconnections
    UserBrowser -->|1. Resolve DNS| DuckDNS
    DuckDNS -->|2. Returns Public IP| UserBrowser
    UserBrowser -->|3. HTTPS Request (Port 443)| SG
    UserBrowser -.->|Port 80 (Unencrypted)| NginxHTTP
    NginxHTTP -->|HTTP 301 Redirect| NginxHTTPS

    SG --> NginxHTTPS
    NginxHTTPS -->|Serve Static Assets| StaticCache
    NginxHTTPS -->|Proxy /api/* & /health| Gunicorn
    Gunicorn --> FlaskBackend
    FlaskBackend <-->|Read / Write Metadata| SQLiteDB
    FlaskBackend -->|Append Audit Records| LocalLog

    %% IAM and Storage
    EC2Role -.->|Provides Temporary IAM Credentials| FlaskBackend
    FlaskBackend -->|4. PutObject (AES256 Encrypted)| S3Bucket
    FlaskBackend -->|5. Generate Presigned URL (Expires in 300s)| UserBrowser
    UserBrowser -->|6. Direct Secure Stream via Presigned URL| S3Bucket

    %% Unauthorized Direct Access Blocked
    UserBrowser -.->|Direct Unsigned S3 URL Access| S3Bucket
    S3Bucket -.->|HTTP 403 Access Denied| UserBrowser

    %% Monitoring Flow
    LocalLog --> CWAgent
    CWAgent -->|Ship Logs| CWLogs
    CWAgent -->|Publish Custom Metrics| CWMetrics
    CWMetrics --> CWAlarm
    CWAlarm -->|Trigger if > 70% for 1 min| SNSTopic
    SNSTopic --> EmailAlert
```

---

## 2. Request Flow Explanations

### Flow 1: Secure Frontend Delivery & Infrastructure Health Polling
1. The user navigates to `https://foodies.duckdns.org/`.
2. The browser initiates a TLS handshake with Nginx on port 443. Nginx presents a valid Let's Encrypt certificate.
3. Nginx serves `index.html` and static files (CSS, JS, images) directly from disk with Gzip compression and caching headers.
4. Health probes (Docker daemon `HEALTHCHECK`, AWS ELB/Route53, or monitoring scripts) ping `GET /health`. Nginx proxies this to the Flask backend on `127.0.0.1:8080`.
5. Flask responds with `HTTP 200 {"status": "ok", "storage_mode": "s3", ...}` verifying operational readiness without cluttering the client UI.

### Flow 2: User Authentication & Role Assignment
1. The user fills the login form at `login.html` and submits credentials.
2. The browser sends `POST /api/auth/login` with email and password over HTTPS.
3. Flask retrieves the hashed password from the SQLite `users` table and evaluates it via `bcrypt.checkpw()`.
4. If valid, Flask sets an **HttpOnly, SameSite=Lax session cookie** containing the user ID and role (`user`, `moderator`, or `admin`).
5. A security audit record (`LOGIN_SUCCESS`) is written to `logs/app.log` with timestamp, client IP, and user identity.

### Flow 3: Restaurant Review & Recipe Sharing (Cloud Object Storage)
1. An authenticated user uploads a restaurant review (e.g. "This restaurant is great!"), a dish review, or a secret recipe at `/reviews.html`.
2. The browser sends a `multipart/form-data` POST request to `/api/reviews`.
3. Flask verifies:
   - Authentication (session presence).
   - Category (`restaurant_review`, `dish_review`, `recipe`) and star rating (1-5).
   - Allowed MIME type and extension (`image/png`, `image/jpeg`, `image/webp`).
   - File size under the 5 MB ceiling.
4. Flask streams the file to Amazon S3 bucket `foodies-cloud-storage` under the key `uploads/<uuid>_<filename>` using `boto3`.
5. The request explicitly specifies `ServerSideEncryption='AES256'`.
6. Flask saves the object metadata, storage key, rating, and author ID to SQLite and records an audit log.

### Flow 4: Secure File Download via Short-Lived Presigned URLs
1. When a user views their uploaded review/recipe, the browser requests `/api/reviews/<id>/file`.
2. Flask performs **Server-Side Data Isolation**:
   - It checks whether `submission.user_id == session['user_id']` OR `session['role'] in ['admin', 'moderator', 'curator']`.
   - If a different user attempts access, Flask returns **HTTP 403 Forbidden** and logs `403_DATA_ISOLATION_BLOCKED`.
3. If authorized, Flask calls S3 `generate_presigned_url('get_object', ExpiresIn=300)` and returns an **HTTP 302 Redirect** to the client.
4. The client browser downloads the object directly from S3 using the cryptographically signed URL. The link expires automatically in 5 minutes.

### Flow 5: Community Moderator Workflow (Keeping Check on the Community)
1. A community moderator (`moderator@foodies.com`) or admin logs in.
2. The frontend detects `session.role in ['moderator', 'admin']` and displays the **Community Moderator Panel**.
3. The moderator reviews pending community posts to prevent spam and verify genuine restaurant reviews and recipes.
4. The moderator clicks **Approve** (updates status to `approved`, displaying it on the public community wall) or **Delete** (permanently deletes the item and removes the object from S3).
5. All moderation actions are logged to `logs/app.log` for auditability.

### Flow 6: IAM Enforcement & Direct S3 Access Blocking
1. If an unauthorized client attempts to access the object directly via the standard Amazon S3 URL (`https://<bucket>.s3.amazonaws.com/uploads/...`):
   - The S3 **Block Public Access** configuration blocks all anonymous reads.
   - The S3 **Bucket Policy** denies any unencrypted or non-HTTPS requests.
   - Amazon S3 returns **HTTP 403 AccessDenied** XML error.
2. The EC2 instance accesses S3 exclusively through the attached **EC2 IAM Role** (`FoodiesEC2Role`). The role policy restricts operations strictly to the `arn:aws:s3:::<bucket>/uploads/*` ARN with no access to any other bucket or AWS services.
