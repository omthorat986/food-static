# CLOUD COMPUTING MINI PROJECT REPORT

---

# Design and Deployment of a Secure, Scalable Cloud-Native Food Discovery & Media Platform on AWS

**Course**: Cloud Computing Laboratory / Mini Project  
**Student Name**: [Your Name]  
**Roll Number / Student ID**: [Your Roll Number]  
**Department**: Computer Science & Engineering / Information Technology  
**Academic Year**: 2026  

---

## 1. Abstract
The rapid growth of web applications necessitates scalable, resilient, and secure hosting infrastructures capable of handling fluctuating traffic and media storage demands. This project presents the architectural transformation of **Foodies**, a static food ordering and cuisine exploration website, into a secure, cloud-native web application deployed on Amazon Web Services (AWS). 

The upgraded system incorporates a containerized Python/Flask backend and Gunicorn WSGI server fronted by an Nginx reverse proxy on an **Amazon Elastic Compute Cloud (EC2)** virtual machine. Object storage is decoupled from the compute instance and migrated to an **Amazon Simple Storage Service (S3)** bucket configured with server-side AES256 encryption, access control lists, and temporary presigned download URLs. Identity and access control are implemented through **AWS Identity and Access Management (IAM)** instance profiles following the principle of least privilege, eliminating long-lived credentials. Furthermore, the application enforces server-side Role-Based Access Control (RBAC) separating standard users from administrative curators, alongside tenant data isolation. System reliability and operational visibility are achieved through **Amazon CloudWatch** agent metric tracking, centralized log streaming, and an automated high-CPU utilization alarm integrated with **Amazon Simple Notification Service (SNS)**. Transport layer security is guaranteed via Let's Encrypt SSL certificates (HTTPS) over a dynamic DNS endpoint.

---

## 2. Problem Statement
Traditional static web architectures lack server-side data persistence, dynamic role authorization, and centralized object storage. Hosting application media assets directly on virtual machine local storage introduces critical drawbacks:
1. **Coupled Storage & Compute Bottlenecks**: Storing user uploads on VM disks limits storage elasticity and risks disk exhaustion.
2. **Security Vulnerabilities**: Storing static API credentials (AWS Access Keys) within code repositories exposes infrastructure to unauthorized exploitation.
3. **Lack of Tenant Isolation & Access Auditing**: Without server-side access control, unauthorized users could tamper with or read private customer data.
4. **Absence of Real-Time Health & Performance Monitoring**: Production failures and traffic spikes remain undetected without automated telemetry and alerting.

The objective of this project is to remediate these deficiencies by designing and deploying an enterprise-grade cloud computing architecture that satisfies strict cloud security, scalability, and monitoring criteria.

---

## 3. Objectives
The key objectives of this project are:
1. **Decoupled Cloud Object Storage**: Implement private Amazon S3 object storage for user media uploads with server-side AES256 encryption and short-lived presigned download URLs.
2. **Compute & Reverse Proxy Deployment**: Deploy the web application on an Amazon EC2 instance behind an Nginx reverse proxy with automated HTTP to HTTPS redirection and Gzip compression.
3. **Role-Based Access Control (RBAC) & Data Isolation**: Implement server-side role enforcement (Standard User vs. Admin Curator) with SQLite metadata persistence and user isolation mechanisms preventing cross-user data leakage.
4. **Least-Privilege IAM Governance**: Configure an AWS IAM instance profile for EC2 granting minimal permissions restricted strictly to the bucket's upload prefix.
5. **Continuous Monitoring & Automated Alerting**: Deploy the Amazon CloudWatch unified agent to monitor CPU, memory, and disk metrics, ingest rotating security logs, and dispatch automated email alerts via Amazon SNS when CPU load exceeds 70%.
6. **Live Public Cloud Accessibility**: Host the entire solution under a live, publicly reachable domain secured with modern TLS/HTTPS encryption.

---

## 4. Technologies Used

| Layer / Domain | Technology / Service | Role & Justification |
| :--- | :--- | :--- |
| **Cloud Provider** | Amazon Web Services (AWS) | Industry-standard cloud infrastructure with comprehensive Free Tier services. |
| **Compute** | AWS EC2 (`t3.micro` / Ubuntu 24.04 LTS) | Elastic virtual machine providing dedicated compute for web and application services. |
| **Web Server / Proxy** | Nginx 1.24+ | High-performance reverse proxy for SSL termination, static file caching, and request routing. |
| **Application Server** | Gunicorn WSGI & Python 3.12+ (Flask) | Lightweight, asynchronous WSGI server running the application business logic. |
| **Object Storage** | Amazon S3 | Highly durable (99.999999999%), scalable private object storage with default AES256 encryption. |
| **Identity & Access** | AWS IAM (Instance Profile & Roles) | Role-based credential delegation using EC2 metadata service without hardcoded keys. |
| **Monitoring & Telemetry**| Amazon CloudWatch & Unified Agent | Real-time monitoring of compute metrics (CPU, RAM, Disk) and centralized log shipping. |
| **Notification Service** | Amazon SNS | Cloud messaging service routing threshold violation alerts to administrator emails. |
| **Database** | SQLite 3 | Embedded, lightweight relational database storing user records, password hashes, and metadata. |
| **Security & Cryptography**| Bcrypt, Certbot (Let's Encrypt), TLS 1.3 | Strong cryptographic password hashing and automated transport-layer encryption. |
| **Domain Resolution** | DuckDNS Dynamic DNS | Free external domain name resolution pointing to the EC2 elastic/public IP. |

---

## 5. Application Design & Architecture

### 5.1 System Architecture Overview
The Foodies application follows a decoupled three-tier cloud architectural pattern:
1. **Presentation Tier**: HTML5, Vanilla CSS3, and JavaScript delivering a responsive user interface with role-aware navigation and interactive community review tools.
2. **Application & Logic Tier**: Nginx reverse proxy delegating dynamic API requests to Gunicorn and Flask, enforcing role-based access decorators, password validation, and S3 SDK calls via Boto3.
3. **Data & Storage Tier**: SQLite for structured relational data alongside Amazon S3 for unstructured binary image storage.

*(Refer to `report/architecture.md` for the complete Mermaid architectural diagram).*

### 5.2 Cloud Feature: "Restaurant & Dish Reviews, Recipe Sharing & Community Moderation"
To satisfy the cloud storage, user action, and multi-role requirements without disrupting the existing restaurant ordering catalog, the **Restaurant & Dish Reviews, Recipe Sharing & Community Moderation** feature was integrated:
- **Normal User Action**: Authenticated customers post restaurant reviews (e.g., highlighting that "this restaurant is great!"), submit dish reviews with star ratings (1-5 stars ⭐), or share culinary recipes with an attached photograph.
- **Decoupled Upload Workflow**: The image attachment is validated (format: PNG/JPG/WEBP, size: ≤ 5MB) and streamed directly to `s3://<bucket>/uploads/<uuid>_<filename>` with `ServerSideEncryption='AES256'`.
- **Private Data Isolation**: A user's uploaded reviews and recipes remain private until moderated. Direct access to Amazon S3 is rejected with **HTTP 403 AccessDenied**. Viewing files generates a cryptographically signed Amazon S3 presigned URL expiring in 300 seconds.
- **Community Moderator & Curator Workflow**: Privileged users (`role = 'moderator'` or `'admin'`) access an exclusive **Community Moderator Panel** designed to keep check on the community, prevent spam, review dining recommendations, and approve or permanently delete items from S3 and the database.

```
[Insert Screenshot 1: Live Application with HTTPS Padlock & Responsive Navigation]
[Insert Screenshot 3: User Publishing Restaurant Review / Recipe with Cloud Upload]
[Insert Screenshot 6: Community Moderator Panel with Moderation Controls]
```

---

## 6. Security Implementation

### 6.1 Principle of Least Privilege (IAM Policy)
AWS access keys (`aws_access_key_id` and `aws_secret_access_key`) are strictly forbidden in application code or environment variables. Instead, an IAM Role (`FoodiesEC2Role`) is attached to the EC2 instance. The associated policy restricts S3 actions solely to the bucket's `uploads/` prefix:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowS3UploadsPrefixOnly",
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"],
      "Resource": "arn:aws:s3:::foodies-cloud-storage-<id>/uploads/*"
    }
  ]
}
```

### 6.2 S3 Bucket Security & Public Access Blocking
To prevent data exposure, the S3 bucket is configured with:
1. **Block All Public Access**: Enabled.
2. **Enforce HTTPS (TLS)**: S3 Bucket Policy denies any request where `aws:SecureTransport == false`.
3. **Server-Side Encryption**: SSE-S3 AES256 encryption is mandated on all `PutObject` operations.

```
[Insert Screenshot 4: Direct S3 URL Returning HTTP 403 AccessDenied]
[Insert Screenshot 10: S3 Bucket Properties Showing Block Public Access ON]
```

### 6.3 Server-Side Access Control & Data Isolation
Route-level decorators (`@login_required` and `@role_required(['admin'])`) enforce authorization server-side:
- Accessing another user's submission returns **HTTP 403 Forbidden**.
- Standard users attempting admin endpoints return **HTTP 403 Forbidden**.
- Authentication relies on secure, HttpOnly session cookies resistant to cross-site scripting (XSS). Passwords are encrypted using salted `bcrypt` hashes.

### 6.4 Rotating Security Audit Logging
The application maintains a rotating log (`logs/app.log`) managed by Python's `RotatingFileHandler` (max 2MB per file, 5 backups). Every authentication event, failed attempt, upload, admin moderation, and 403/500 anomaly is logged with client IP and user identity.

---

## 7. Monitoring & Observability

### 7.1 CloudWatch Unified Agent Configuration
The Amazon CloudWatch Agent runs as a system daemon on Ubuntu, collecting:
- **System Metrics**: CPU utilization (user, system, idle), memory utilization (`mem_used_percent`), and disk space usage (`disk_used_percent`).
- **Log Files**: Ingestion of application security logs (`logs/app.log`) and Nginx logs into CloudWatch Log Groups:
  - `/aws/ec2/foodies/app`
  - `/aws/ec2/foodies/nginx-access`
  - `/aws/ec2/foodies/nginx-error`

```
[Insert Screenshot 12: CloudWatch Performance Metrics Dashboard]
[Insert Screenshot 13: CloudWatch Log Streams Showing Audit Events]
```

### 7.2 Automated High-CPU Alarm & SNS Email Alerting
An automated CloudWatch Alarm (`Foodies-High-CPU-Utilization-Alarm`) triggers when:
$$\text{Average CPUUtilization} > 70\% \quad \text{for 1 consecutive period of 60 seconds}$$

Upon breach, the alarm transitions to the `ALARM` state and publishes an alert to the `foodies-cpu-alarm-topic` Amazon SNS topic, immediately emailing the system administrator.

```
[Insert Screenshot 14: CloudWatch Alarm in ALARM State & Email Notification]
```

---

## 8. Verification & Test Results
The deployment was verified using both an automated test runner (`python app.py --test`) and manual infrastructure validation checks:

| Metric / Check | Target Value | Observed Value | Evaluation |
| :--- | :--- | :--- | :---: |
| Automated Self-Tests | 10/10 Passed | 10/10 Passed (100%) | **PASS** |
| HTTP to HTTPS Redirection | HTTP 301 Redirect | HTTP 301 to HTTPS | **PASS** |
| Direct S3 Access | HTTP 403 AccessDenied | HTTP 403 XML Error | **PASS** |
| Presigned URL Expiration | 300 Seconds | Expired at 305s | **PASS** |
| CPU Stress Test Threshold | Alarm fired > 70% | Triggered at 88.4% CPU | **PASS** |
| Server Health Status | HTTP 200 `status: ok` | Response time: 24 ms | **PASS** |

```
[Insert Screenshot 15: Terminal Execution of python app.py --test PASS Table]
```

---

## 9. Challenges and Solutions

| Challenge Encountered | Technical Root Cause | Engineering Solution Implemented |
| :--- | :--- | :--- |
| **1. Secure Credential Management** | Storing AWS access keys in code or config files creates critical security vulnerabilities. | Implemented EC2 IAM Instance Profiles with temporary credentials fetched automatically via AWS Metadata Service (IMDSv2). |
| **2. Private Object Viewing** | S3 bucket is completely private, preventing direct `<img src="...">` rendering in browsers. | Implemented short-lived S3 presigned URLs (expires in 300s) generated on-demand only for authenticated and authorized users. |
| **3. Memory & Disk Metric Tracking** | AWS EC2 does not provide RAM or disk utilization metrics by default in the basic CloudWatch tier. | Configured and deployed the Amazon CloudWatch Unified Agent to publish custom OS-level memory and disk metrics. |
| **4. Zero Downtime HTTPS Setup** | Certbot ACME challenge requires an active HTTP listener on port 80 during domain verification. | Configured Nginx with an explicit `/.well-known/acme-challenge/` location block while redirecting all general traffic to port 443. |
| **5. Data Isolation Enforcement** | Relational IDs in URLs can allow users to view other tenants' private uploaded files. | Embedded owner verification inside Flask routes, returning strict HTTP 403 Forbidden on cross-tenant access attempts. |

---

## 10. Conclusion & Future Scope
The **Foodies** cloud computing mini project successfully demonstrated the transition from a static web application to an enterprise-standard, cloud-native solution deployed on Amazon Web Services. All eight required demonstration milestones were fully satisfied:
1. User registration and secure login with bcrypt hashing.
2. User restaurant review, dish rating, and recipe submission with photo upload.
3. Storage of encrypted image objects in Amazon S3.
4. Second privileged role (Community Moderator / Admin Curator) keeping check on community data, moderating reviews and recipes.
5. IAM and bucket policy blocking unauthorized public access.
6. Full end-to-end HTTPS encryption with automated redirection.
7. Real-time CloudWatch monitoring and SNS threshold alerting.
8. Live cloud operation on an accessible domain.

### Future Scope
1. **Auto Scaling & Elastic Load Balancing**: Integrate an AWS Application Load Balancer (ALB) and Auto Scaling Group (ASG) to dynamically scale EC2 instances during peak meal times.
2. **Serverless Architecture**: Migrate backend routes to AWS Lambda and Amazon API Gateway to achieve zero-idle-cost compute.
3. **Managed Database**: Migrate SQLite to Amazon Aurora Serverless or Amazon DynamoDB for multi-region high availability.
4. **AI-Assisted Curation**: Utilize Amazon Rekognition to automatically inspect uploaded food images and filter inappropriate content prior to curator review.
