# Screenshots Checklist for Project Report & Demo Submission

This checklist outlines the exact set of screenshots required for the project report and final presentation. Capture these screenshots after completing deployment to AWS.

---

## Redaction Guidelines
Before inserting screenshots into your final report or slides:
- **Redact**: 12-digit AWS Account ID (top-right navigation bar in AWS Console).
- **Redact**: SSH private key filename and local directory paths.
- **Redact**: Credit card numbers or account balances in billing dashboards.
- **Keep Visible**: DuckDNS live URL, HTTPS padlock, IAM role name, S3 bucket name, and status pills.

---

## Numbered Screenshots Checklist

### 1. Live Application Running on Cloud URL (HTTPS)
- **Where**: Web Browser.
- **URL**: `https://<your-subdomain>.duckdns.org/`
- **What Must Be Visible**:
  - Browser address bar showing the valid **HTTPS padlock icon**.
  - The live DuckDNS domain name.
  - Clean, modern navigation bar with Reviews & Recipes link and user greeting/role badge.

### 2. User Authentication & Session Establishment
- **Where**: Web Browser (`/login.html`).
- **What Must Be Visible**:
  - Login form with email and password filled.
  - Green toast message: `"Login successful! Redirecting..."`.
  - In Developer Tools -> **Application** -> **Cookies**: The `session` cookie with `HttpOnly` and `SameSite=Lax` flags checked.

### 3. User Data Creation & Cloud File Upload (Review & Recipe Sharing)
- **Where**: Web Browser (`/reviews.html`).
- **What Must Be Visible**:
  - The "Share a Review or Recipe" form filled with category (e.g. 🍽️ Restaurant Review), restaurant/dish title, rating (⭐⭐⭐⭐⭐), review text ("This restaurant is great!"), and attached image.
  - Successful upload confirmation banner: `"Published successfully! Your review/recipe is encrypted and awaiting community moderator approval."`
  - In "My Reviews & Shared Recipes", the newly created card showing filename, category, rating, and status `PENDING`.

### 4. Direct S3 Public Access Denied (Security & IAM Proof)
- **Where**: Web Browser or Terminal (`curl`).
- **URL**: `https://<your-bucket-name>.s3.amazonaws.com/uploads/<file-key>`
- **What Must Be Visible**:
  - The browser displaying an Amazon S3 XML error page:
    ```xml
    <Error>
      <Code>AccessDenied</Code>
      <Message>Access Denied</Message>
    </Error>
    ```
  - Proves that the S3 bucket is strictly private and public access is blocked.

### 5. Authorized Presigned URL File Access
- **Where**: Web Browser (`/reviews.html`).
- **What Must Be Visible**:
  - User clicking **"View Attachment (Cloud URL)"**.
  - Browser address bar showing the Amazon S3 presigned URL containing:
    `?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=...&X-Amz-Expires=300&X-Amz-Signature=...`
  - The uploaded restaurant/dish image rendering properly in the browser.

### 6. Role-Aware Community Moderator Panel (Keeping Check on the Community)
- **Where**: Web Browser (`/reviews.html`).
- **What Must Be Visible**:
  - Top navigation showing: `Hello, Community Moderator` with the blue `[COMMUNITY MODERATOR]` badge.
  - The **Community Moderator Panel** visible on the page (hidden for standard users).
  - The moderation table displaying user emails, review/recipe title, category badge, and action buttons (`Approve`, `Reject`, `Delete`).

### 7. Private Data Isolation (Normal User Blocked)
- **Where**: Web Browser or Terminal.
- **What Must Be Visible**:
  - User B attempting to view User A's private review/recipe ID via URL or API (`GET /api/reviews/<user_a_id>`).
  - The response returning **HTTP 403 Forbidden**:
    `{"error": "Forbidden: You do not have permission to access another user's submission."}`.

### 8. AWS EC2 Instance Dashboard
- **Where**: AWS EC2 Management Console -> **Instances**.
- **What Must Be Visible**:
  - Instance name: `foodies-production-vm`.
  - Instance state: **Running**.
  - Instance type: `t3.micro` (or `t2.micro`).
  - Public IPv4 address.
  - IAM Role attached: `FoodiesEC2Role`.

### 9. EC2 Security Group Inbound Rules
- **Where**: AWS EC2 Console -> **Security Groups** -> `foodies-web-sg`.
- **What Must Be Visible**:
  - Port `443` (HTTPS) | Source: `0.0.0.0/0` (Anywhere).
  - Port `80` (HTTP) | Source: `0.0.0.0/0` (Anywhere).
  - Port `22` (SSH) | Source: `<Your-IP>/32` (Restricted).

### 10. Amazon S3 Bucket Configuration & Default Encryption
- **Where**: AWS S3 Console -> Bucket -> **Properties & Permissions**.
- **What Must Be Visible**:
  - Bucket name: `foodies-cloud-storage-...`.
  - **Block all public access**: **On**.
  - Default encryption: **Server-side encryption with Amazon S3 managed keys (SSE-S3 / AES256)**.
  - S3 Bucket Policy enforcing TLS (HTTPS) transport.

### 11. AWS IAM Role & Least-Privilege Policy
- **Where**: AWS IAM Console -> **Roles** -> `FoodiesEC2Role`.
- **What Must Be Visible**:
  - Attached policy: `FoodiesEC2S3CloudWatchPolicy`.
  - Policy JSON showing resource restriction strictly to `arn:aws:s3:::<bucket>/uploads/*`.
  - Absence of hardcoded AWS Access Keys (`aws_access_key_id`) anywhere in the code.

### 12. Amazon CloudWatch Metrics Dashboard
- **Where**: AWS CloudWatch Console -> **Dashboards** -> `Foodies-Performance-Dashboard`.
- **What Must Be Visible**:
  - Live metric graphs showing `CPUUtilization` (%), `mem_used_percent` (%), and `disk_used_percent` (%).
  - Demonstrates continuous virtual machine monitoring.

### 13. Amazon CloudWatch Logs Ingestion
- **Where**: AWS CloudWatch Console -> **Log groups** -> `/aws/ec2/foodies/app`.
- **What Must Be Visible**:
  - Log streams displaying timestamped application audit records:
    `AUDIT | LOGIN_SUCCESS | ...`
    `AUDIT | UPLOAD_SUCCESS | key='uploads/...'`
    `AUDIT | ADMIN_STATUS_CHANGE | ...`
    `AUDIT | 403_FORBIDDEN | ...`

### 14. CloudWatch CPU Alarm & Email Notification (SNS)
- **Where**: AWS CloudWatch Console -> **Alarms** AND Student Email Inbox.
- **What Must Be Visible**:
  - CloudWatch Alarm: `Foodies-High-CPU-Utilization-Alarm` showing threshold: `CPUUtilization > 70 for 1 datapoints within 1 minute`.
  - Email notification received from AWS Notifications:
    `"You are receiving this email because your Amazon CloudWatch Alarm "Foodies-High-CPU-Utilization-Alarm" in the US East (N. Virginia) region has entered the ALARM state..."`.

### 15. Automated Self-Test PASS Table Execution
- **Where**: Terminal / SSH session on EC2.
- **Command**: `python3 app.py --test`
- **What Must Be Visible**:
  - The complete ASCII table showing **10/10 tests PASS**:
    `TC-01` through `TC-10` with `PASS` status.
  - Summary output: `"RESULT: ALL SELF-TESTS PASSED SUCCESSFULLY! (PASS)"`.
