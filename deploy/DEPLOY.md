# Foodies AWS Production Deployment Guide (Ubuntu 24.04 LTS)

This runbook provides complete, step-by-step instructions for deploying the **Foodies** application on AWS in a hardened, production-grade architecture.

---

## Architecture Overview
- **OS**: Ubuntu 24.04 LTS on AWS EC2 (`t3.micro`, Free Tier eligible)
- **Security Group**: Inbound ports 22 (Admin IP only), 80 (HTTP / ACME challenge), 443 (HTTPS)
- **Firewall Strategy**: AWS Security Group functions as the stateful firewall. **UFW is skipped** to avoid redundant filtering and prevent accidental SSH lockouts.
- **IMDSv2**: Enforced (`HttpTokens=required`, HopLimit=1) to prevent SSRF credential theft
- **Web Server / Reverse Proxy**: Nginx with `server_tokens off`, strict deny rules, rate-limited `/api/auth/`, ACME challenge webroot (`/var/www/certbot`), and static caching
- **Application Server**: Python 3.12 + Gunicorn (`Type=simple`, `foodies:foodies`, mode 750) managed by `systemd` with `ReadWritePaths`
- **Secrets Management**: `/etc/foodies/foodies.env` (owner `root:foodies`, mode 640), loaded via `EnvironmentFile`
- **Database**: SQLite at `/var/lib/foodies/foodies.db` (outside document root, mode 750)
- **Object Storage**: Private Amazon S3 bucket (`uploads/*` prefix only, TLS-enforced, AES256 server-side encryption, presigned URLs)
- **IAM**: EC2 IAM Role with least-privilege policy (S3 prefix-constrained, CloudWatch metrics & logs)
- **SSL / TLS**: Free Let's Encrypt TLS certificate via Certbot webroot mode (renewals run without stopping Nginx)
- **DNS**: Free dynamic DNS via DuckDNS pointing to an Elastic IP
- **Monitoring**: AWS CloudWatch Agent (shipping App, Gunicorn, and Nginx logs) with CPU alarms and SNS email notifications

---

## Deployment Steps (Strict Sequence)

### Step 1: Create the Amazon S3 Bucket
1. Open the [AWS S3 Console](https://s3.console.aws.amazon.com/).
2. Click **Create bucket**:
   - **Bucket name**: `foodies-uploads-2026` (must be globally unique across all AWS accounts).
   - **AWS Region**: Select your target region (e.g., `us-east-1` or `ap-south-1`).
   - **Block Public Access**: Keep **"Block all public access" ENABLED (Checked)**.
   - **Default Encryption**: **Server-side encryption with Amazon S3 managed keys (SSE-S3 / AES256)**.
   - **Bucket Key**: Enabled.
3. Click **Create bucket**.
4. Open the newly created bucket, click the **Permissions** tab:
   - Scroll down to **Bucket Policy** and click **Edit**.
   - Copy the contents of `deploy/s3-bucket-policy.json` (configured with `foodies-uploads-2026`).
   - Click **Save changes**.

> [!NOTE]
> **Manual AWS Console Uploads Must Use SSE-S3:**
> The bucket policy strictly enforces `s3:x-amz-server-side-encryption: AES256`. If uploading test images or objects via the AWS S3 Console, under **Properties** -> **Server-side encryption settings**, you must explicitly select **"Specify an encryption key"** and choose **"Server-side encryption with Amazon S3 managed keys (SSE-S3)"**. Otherwise, the console upload will be rejected with HTTP 403 Access Denied. (The Foodies application code automatically attaches this SSE-S3 encryption header to all programmatic uploads).

---

### Step 2: Create the IAM Role for EC2
1. Open the [AWS IAM Console](https://console.aws.amazon.com/iam/).
2. Under **Access management**, select **Policies** -> **Create policy**:
   - Choose the **JSON** editor.
   - Paste the contents of `deploy/iam-policy.json` (configured with `foodies-uploads-2026`).
   - Click **Next**. Name the policy: `FoodiesEC2S3CloudWatchPolicy`.
   - Click **Create policy**.
3. Under **Access management**, select **Roles** -> **Create role**:
   - **Trusted entity type**: AWS service.
   - **Use case**: EC2. Click **Next**.
   - **Permissions policies**: Search and attach `FoodiesEC2S3CloudWatchPolicy`.
   - Also search and attach the AWS managed policy: **`CloudWatchAgentServerPolicy`** (grants standard CloudWatch agent permissions for metrics and logs).
   - Name the role: `FoodiesEC2Role`.
   - Click **Create role**.

---

### Step 3: Configure the EC2 Security Group
> [!NOTE]
> **Why skip UFW?**
> The AWS EC2 Security Group operates at the hypervisor level as a high-performance stateful firewall. Enabling `ufw` inside Ubuntu 24.04 adds redundant kernel filtering and risks permanent SSH lockout during configuration. Skip `ufw` entirely.

1. Open the [AWS EC2 Console](https://console.aws.amazon.com/ec2/) -> **Security Groups** -> **Create security group**.
2. **Security group name**: `foodies-web-sg`.
3. **Description**: `Inbound HTTP/HTTPS and restricted SSH for Foodies`.
4. Configure **Inbound rules**:
   - **Rule 1 (SSH)**: Type: `SSH` | Port: `22` | Source: `My IP` (e.g. `203.0.113.45/32`). Never use `0.0.0.0/0`.
   - **Rule 2 (HTTP)**: Type: `HTTP` | Port: `80` | Source: `Anywhere-IPv4 (0.0.0.0/0)` (required for ACME challenge & HTTPS redirect).
   - **Rule 3 (HTTPS)**: Type: `HTTPS` | Port: `443` | Source: `Anywhere-IPv4 (0.0.0.0/0)` (secure user traffic).
5. Configure **Outbound rules**:
   - Default: All traffic to `0.0.0.0/0`.
6. Click **Create security group**.

---

### Step 4: Launch EC2 Instance with IMDSv2 Enforced
1. In the EC2 Console, click **Launch Instances**:
   - **Name**: `foodies-production-server`.
   - **AMI**: **Ubuntu Server 24.04 LTS (HVM)**, SSD Volume Type (64-bit x86).
   - **Instance type**: `t3.micro` (or `t2.micro`).
   - **Key pair**: Select or create an SSH key pair (`.pem`).
   - **Network settings**: Select the `foodies-web-sg` security group created in Step 3.
2. Expand **Advanced details**:
   - **IAM instance profile**: Select `FoodiesEC2Role`.
   - **Metadata accessible**: Enabled.
   - **Metadata version (IMDS)**: Select **V2 only (token required)** (`HttpTokens=required`).
   - **Metadata response hop limit**: `1` (prevents SSRF token extraction from inside containers or proxies).
3. Click **Launch instance**.

---

### Step 5: Allocate and Associate an Elastic IP
1. In the EC2 Console, go to **Network & Security** -> **Elastic IPs**.
2. Click **Allocate Elastic IP address** -> Click **Allocate**.
3. Select the allocated IP, click **Actions** -> **Associate Elastic IP address**:
   - **Resource type**: Instance.
   - **Instance**: Select your `foodies-production-server`.
   - Click **Associate**.
4. Note this static public IPv4 address. It will remain unchanged across instance reboots.

---

### Step 6: Configure DuckDNS Domain
1. Log in to [DuckDNS](https://www.duckdns.org/).
2. In the **domains** section, add your subdomain: e.g. `my-foodies`.
3. In the **ip** field, enter the **Elastic IP** address from Step 5.
4. Click **update ip**.
5. Your domain name is now `my-foodies.duckdns.org`. Verify DNS resolution:
   ```bash
   dig +short my-foodies.duckdns.org
   ```

---

### Step 7: Clone Application Code into ~/foodies-repo with Read-Only Deploy Key
1. Connect to the EC2 instance via SSH:
   ```bash
   chmod 400 your-key.pem
   ssh -i your-key.pem ubuntu@<ELASTIC_IP>
   ```

2. Generate a dedicated read-only SSH deploy key on the server:
   ```bash
   ssh-keygen -t ed25519 -C "foodies-deploy-key" -f ~/.ssh/id_ed25519_deploy -N ""
   cat ~/.ssh/id_ed25519_deploy.pub
   ```
3. Go to your GitHub repository -> **Settings** -> **Deploy keys** -> **Add deploy key**:
   - Title: `EC2-Production-ReadOnly`.
   - Paste the public key. Leave **"Allow write access" UNCHECKED**. Click **Add key**.

4. Clone the repository into `~/foodies-repo`:
   ```bash
   GIT_SSH_COMMAND="ssh -i $HOME/.ssh/id_ed25519_deploy -o IdentitiesOnly=yes" \
       git clone git@github.com:YOUR_GITHUB_USER/YOUR_REPO.git ~/foodies-repo
   ```
   *(Cloning into `~/foodies-repo` keeps your git repository intact and avoids collision with `/opt/foodies`, which holds production runtime files and the dedicated virtual environment).*

---

### Step 8: Bootstrap the Ubuntu 24.04 Host
Run the automated bootstrap script directly from your cloned repository:
```bash
sudo bash ~/foodies-repo/deploy/scripts/bootstrap.sh
```

> [!NOTE]
> **Server Runtime (Python 3.12):**
> Ubuntu 24.04 LTS comes standard with Python 3.12 (`python3 --version` returns Python 3.12.x). The virtual environment initialized at `/opt/foodies/venv` uses this system Python 3.12 installation, and all pinned dependencies in `requirements.txt` are tested and verified for Python 3.12 compatibility.

*What this script does:*
- **Swap Space**: Configures a 2GB swap file (`/swapfile`) to prevent Out-Of-Memory (OOM) errors during `pip install` and Gunicorn operation on `t3.micro` (1GB RAM).
- **Packages**: Installs `nginx`, `git`, `rsync`, `certbot`, `python3-venv`, `python3-pip`, `sqlite3`, `curl`.
- **System Accounts**: Creates system user and group `foodies:foodies`.
- **Production Directories**: Creates `/opt/foodies`, `/var/lib/foodies`, `/var/log/foodies` (mode 750, `foodies:foodies`), `/etc/foodies` (mode 750, `root:foodies`), and ACME webroot `/var/www/certbot` (mode 755, `www-data:www-data`).
- **Nginx & CloudWatch Permissions**: Adds `www-data` to the `foodies` group and **restarts Nginx** so active worker processes pick up supplementary group permissions. Adds `cwagent` to `foodies` and `adm` groups, restarting `amazon-cloudwatch-agent` if it exists.
- **Virtual Environment**: Initializes an isolated virtual environment at `/opt/foodies/venv`.

---

### Step 9: Deploy Application Code with update-foodies.sh
Run the dedicated deployment/sync script to deploy code into `/opt/foodies`:
```bash
sudo bash ~/foodies-repo/deploy/scripts/update-foodies.sh ~/foodies-repo
```
*What this script does:*
1. Syncs application files from `~/foodies-repo` into `/opt/foodies` (preserving the existing `/opt/foodies/venv`).
2. Enforces strict file ownership (`foodies:foodies`) and permissions (mode 750).
3. Installs pinned dependencies via `/opt/foodies/venv/bin/pip install -r requirements.txt`.
4. Runs schema migrations (`manage.py migrate`) idempotently.
5. Safely reloads or restarts `foodies.service` if active.

> [!TIP]
> You will use this exact command (`sudo bash ~/foodies-repo/deploy/scripts/update-foodies.sh ~/foodies-repo`) every time you pull code updates in `~/foodies-repo`!

---

### Step 10: Configure Production Environment Secrets
1. Copy the environment template to `/etc/foodies/foodies.env`:
   ```bash
   sudo cp /opt/foodies/.env.example /etc/foodies/foodies.env
   sudo chown root:foodies /etc/foodies/foodies.env
   sudo chmod 640 /etc/foodies/foodies.env
   ```

2. Generate a secure, random 32-character secret key:
   ```bash
   openssl rand -hex 32
   ```

3. Edit `/etc/foodies/foodies.env` with your production values:
   ```ini
   APP_ENV=production
   SECRET_KEY=<PASTE_GENERATED_32_CHAR_HEX_KEY>
   STORAGE_MODE=s3
   S3_BUCKET=foodies-uploads-2026
   AWS_REGION=us-east-1
   DATABASE_PATH=/var/lib/foodies/foodies.db
   COOKIE_SECURE=true
   ALLOWED_HOSTS=my-foodies.duckdns.org,localhost,127.0.0.1
   ```

---

### Step 11: Create Admin Account & Run Test Suites in Server Virtualenv
1. Create the production administrator account (prompts with `getpass`, enforces 10+ characters):
   ```bash
   sudo -u foodies /opt/foodies/venv/bin/python /opt/foodies/manage.py create-admin
   ```
   Enter the admin email and a strong password (at least 10 characters).

2. **Verify application inside the server virtual environment**:
   Run both automated test suites directly in `/opt/foodies/venv` to ensure all dependencies, security rules, and database routines function on the production host:
   ```bash
   # 1. Run manage.py automated self-tests
   sudo -u foodies /opt/foodies/venv/bin/python /opt/foodies/manage.py test

   # 2. Run unittest discovery
   sudo -u foodies /opt/foodies/venv/bin/python -m unittest discover -s /opt/foodies/tests -v
   ```
   Both test suites must pass 100% before proceeding.

---

### Step 12: Configure HTTP-Only Nginx (Starts Cleanly Before Certificates)
1. Copy the initial HTTP-only Nginx configuration:
   ```bash
   sudo cp /opt/foodies/deploy/nginx.conf /etc/nginx/sites-available/foodies.conf
   ```

2. Update `server_name` with your DuckDNS domain:
   ```bash
   sudo sed -i 's/YOUR_DOMAIN_NAME/my-foodies.duckdns.org/g' /etc/nginx/sites-available/foodies.conf
   ```

3. Enable the site and disable default site:
   ```bash
   sudo ln -sf /etc/nginx/sites-available/foodies.conf /etc/nginx/sites-enabled/
   sudo rm -f /etc/nginx/sites-enabled/default
   ```

4. **Test Nginx configuration with `sudo nginx -t` before starting Nginx**:
   ```bash
   sudo nginx -t
   ```
   *Verification:* `sudo nginx -t` must output `syntax is ok` and `test is successful`.

5. Start / restart Nginx:
   ```bash
   sudo systemctl restart nginx
   ```

---

### Step 13: Obtain TLS Certificate via Certbot Webroot
Run Certbot in **webroot mode** targeting `/var/www/certbot`:
> [!IMPORTANT]
> Use `--webroot -w /var/www/certbot`, **NOT `--standalone`**! Webroot mode allows Let's Encrypt to verify domain ownership while Nginx remains active on port 80, enabling seamless automated renewals without downtime.

```bash
sudo certbot certonly \
    --webroot \
    -w /var/www/certbot \
    -d my-foodies.duckdns.org \
    --agree-tos \
    --no-eff-email \
    -m your-email@example.com
```

Test automated renewal (Nginx continues running):
```bash
sudo certbot renew --dry-run
```

---

### Step 14: Enable Full HTTPS Nginx Block & Start Systemd Service
1. Enable the production HTTPS Nginx configuration:
   ```bash
   sudo cp /opt/foodies/deploy/nginx-https.conf /etc/nginx/sites-available/foodies.conf
   sudo sed -i 's/YOUR_DOMAIN_NAME/my-foodies.duckdns.org/g' /etc/nginx/sites-available/foodies.conf
   sudo nginx -t
   sudo systemctl reload nginx
   ```

2. Install and start the Gunicorn systemd service (configured with 2 workers for `t3.micro`):
   ```bash
   sudo cp /opt/foodies/deploy/foodies.service /etc/systemd/system/foodies.service
   sudo systemctl daemon-reload
   sudo systemctl enable --now foodies.service
   sudo systemctl status foodies.service
   ```

---

### Step 15: Install and Start AWS CloudWatch Agent
1. Download and install the official Amazon CloudWatch agent package:
   ```bash
   wget -q https://amazoncloudwatch-agent.s3.amazonaws.com/ubuntu/amd64/latest/amazon-cloudwatch-agent.deb
   sudo dpkg -i -E ./amazon-cloudwatch-agent.deb
   rm -f ./amazon-cloudwatch-agent.deb
   ```

2. Start the CloudWatch agent using the repository configuration:
   ```bash
   sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \
       -a fetch-config \
       -m ec2 \
       -c file:/opt/foodies/deploy/cloudwatch-agent-config.json \
       -s
   ```

3. Verify agent status:
   ```bash
   sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a status
   ```

---

### Step 16: Setup CloudWatch Alarms & SNS Alerting
1. Open the [AWS CloudWatch Console](https://console.aws.amazon.com/cloudwatch/) -> **Alarms** -> **Create alarm**.
2. **Select metric**: `EC2` -> `Per-Instance Metrics` -> Select your instance's `CPUUtilization`.
3. Set condition: **Static threshold**, Greater than `70%` for `5 minutes` (1 consecutive period).
4. Configure actions:
   - Select **Send notification to an SNS topic**.
   - Create new topic: `FoodiesAlerts`.
   - Enter your email address.
   - Click **Create topic**.

> [!WARNING]
> ### CRITICAL SNS EMAIL CONFIRMATION WARNING
> When you create an SNS email subscription, AWS sends an email with the subject:
> **"AWS Notification - Subscription Confirmation"**
>
> You **MUST open this email and click "Confirm subscription"**!
> Until you click that link, the subscription status remains `PendingConfirmation`, and **no email alerts will be delivered when alarms fire**!

---

### Step 17: Execute Automated Post-Deployment Smoke Test
Run the automated verification script:
```bash
sudo bash /opt/foodies/deploy/scripts/smoke-test.sh my-foodies.duckdns.org foodies-uploads-2026 us-east-1
```
*The smoke test validates:*
1. `GET /health` returns 200 OK and `status: "ok"`.
2. `GET /ready` returns 200 OK and `database: "ok"`.
3. HTTP to HTTPS 301 redirection works.
4. Security headers are present on all responses (`X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`, `Referrer-Policy`, `Permissions-Policy`, `Strict-Transport-Security`, CSP without inline scripts).
5. Information leakage prevention: sensitive paths (`/app.py`, `/foodies.db`, `/.env`, `/logs/app.log`, `/requirements.txt`, `/.git/config`, `/deploy/nginx.conf`) all return **404 Not Found**.
6. Private S3 isolation: raw direct object URL returns **403 AccessDenied**.

---

### Step 18: Setup Automated SQLite Backups
Set up a daily automated backup of the SQLite database using SQLite's online `.backup` command (locks safe):
```bash
sudo mkdir -p /var/lib/foodies/backups
sudo chown foodies:foodies /var/lib/foodies/backups
sudo chmod 750 /var/lib/foodies/backups

# Add cron job to backup daily at 03:00 AM
echo '0 3 * * * foodies sqlite3 /var/lib/foodies/foodies.db ".backup '\''/var/lib/foodies/backups/foodies-$(date +\%F).db'\''" && find /var/lib/foodies/backups/ -name "foodies-*.db" -mtime +14 -delete' | sudo tee /etc/cron.d/foodies-backup
```

---

### Step 19: Security Cleanup
1. Remove deploy key from the user directory if no longer needed:
   ```bash
   rm -f ~/.ssh/id_ed25519_deploy*
   ```
2. Verify file permissions:
   ```bash
   sudo ls -ld /opt/foodies /var/lib/foodies /var/log/foodies /etc/foodies
   sudo ls -l /etc/foodies/foodies.env
   ```
   - `/opt/foodies`: `drwxr-x--- foodies foodies` (mode 750)
   - `/var/lib/foodies`: `drwxr-x--- foodies foodies` (mode 750)
   - `/var/log/foodies`: `drwxr-x--- foodies foodies` (mode 750)
   - `/etc/foodies/foodies.env`: `-rw-r----- root foodies` (mode 640)
3. Clear bash history:
   ```bash
   history -c
   ```

---

## Step 20: Troubleshooting & Diagnostic Guide

Always test Nginx configuration before restarting or reloading:
```bash
sudo nginx -t
```
If `nginx -t` passes with `syntax is ok` and `test is successful`, apply changes with `sudo systemctl reload nginx`. If it fails, read the error message line number and inspect that configuration file before restarting.

### Troubleshooting Quick-Reference Table

| Symptom / Error | Root Cause | Diagnostic & Resolution Steps |
| :--- | :--- | :--- |
| **`sudo nginx -t` fails with directive syntax error** | Typos, unclosed curly braces, or missing semicolons in `/etc/nginx/sites-available/foodies.conf`. | 1. Check exact error output for file and line number.<br>2. Run `sudo nginx -t` to locate the offending token.<br>3. Verify all directive lines end with `;`. |
| **`sudo nginx -t` fails: cannot load certificate** | `deploy/nginx-https.conf` was applied BEFORE Certbot ran, so `/etc/letsencrypt/live/...` does not exist. | 1. Revert to HTTP-only config: `sudo cp /opt/foodies/deploy/nginx.conf /etc/nginx/sites-available/foodies.conf`.<br>2. Replace domain with `sed`.<br>3. Run `sudo nginx -t && sudo systemctl restart nginx`.<br>4. Run Certbot (Step 13), then apply HTTPS config (Step 14). |
| **HTTP 502 Bad Gateway** | Gunicorn backend service is down or failing to bind to `127.0.0.1:8080`. | 1. Check service status: `sudo systemctl status foodies.service`.<br>2. Inspect recent logs: `sudo journalctl -u foodies.service -n 50 --no-pager`.<br>3. Check error log: `sudo cat /var/log/foodies/error.log`.<br>4. Verify `/etc/foodies/foodies.env` exists and contains valid `SECRET_KEY`. |
| **HTTP 403 Forbidden on static assets (`/index.html`, `/css/*`)** | `www-data` user lacks read permissions on `/opt/foodies` (missing `foodies` group membership or Nginx wasn't restarted). | 1. Add `www-data` to `foodies` group: `sudo usermod -a -G foodies www-data`.<br>2. **Restart Nginx** so active worker processes pick up the group: `sudo systemctl restart nginx`.<br>3. Verify ownership: `ls -ld /opt/foodies` (must be `foodies:foodies`, mode 750). |
| **`pip install` killed or process terminates with `Killed` (OOM)** | Server ran out of memory on `t3.micro` (1GB RAM) during package compilation or wheel building. | 1. Check swap: `swapon --show` or `free -h`.<br>2. Create 2GB swap: `sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile`.<br>3. Re-run `sudo bash ~/foodies-repo/deploy/scripts/update-foodies.sh ~/foodies-repo`. |
| **Certbot fails ACME challenge: `Invalid response ... 404`** | Port 80 is blocked in EC2 Security Group, DuckDNS IP doesn't match Elastic IP, or ACME webroot directory is missing. | 1. Verify DNS: `dig +short my-foodies.duckdns.org` matches your Elastic IP.<br>2. Verify Inbound Rule: AWS Security Group allows port 80 from `0.0.0.0/0`.<br>3. Verify directory: `ls -ld /var/www/certbot` (must exist and be mode 755).<br>4. Test locally: `curl -I http://127.0.0.1/.well-known/acme-challenge/test`. |
| **S3 Upload / Ready Probe returns 503 or 403 AccessDenied** | EC2 instance lacks `FoodiesEC2Role` IAM role, bucket name mismatch, or bucket policy denies access. | 1. In EC2 Console, ensure `FoodiesEC2Role` is attached as IAM instance profile.<br>2. Verify `/etc/foodies/foodies.env` has exact `S3_BUCKET` name (`foodies-uploads-2026`).<br>3. Check IAM policy: ensures `s3:PutObject` on `arn:aws:s3:::foodies-uploads-2026/uploads/*` and `s3:ListBucket` with prefix condition.<br>4. Check `/ready` probe: `curl -s http://127.0.0.1:8080/ready`. |
| **Database `sqlite3.OperationalError: unable to open database file`** | `/var/lib/foodies` directory does not exist or has incorrect ownership. | 1. Verify directory: `sudo mkdir -p /var/lib/foodies`.<br>2. Set ownership: `sudo chown -R foodies:foodies /var/lib/foodies && sudo chmod 750 /var/lib/foodies`.<br>3. Run migration: `sudo -u foodies /opt/foodies/venv/bin/python /opt/foodies/manage.py migrate`. |
| **HTTP 403 CSRF Token Missing or Invalid on login/register** | Client POSTed state-changing request without `X-CSRFToken` header or valid session cookie. | 1. Ensure client fetches `/api/auth/csrf-token` before POSTing.<br>2. If using browser forms, ensure CSRF token cookie is included in request headers. |
| **CloudWatch Agent fails to start or publish metrics** | Missing IAM policy permissions (`cloudwatch:PutMetricData`, `logs:PutLogEvents`) or config syntax error. | 1. Check agent logs: `sudo tail -n 50 /opt/aws/amazon-cloudwatch-agent/logs/amazon-cloudwatch-agent.log`.<br>2. Verify IAM policy includes CloudWatch and logs permissions.<br>3. Test config syntax: `python3 -m json.tool /opt/foodies/deploy/cloudwatch-agent-config.json`. |
