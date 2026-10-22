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
   - **Bucket name**: `YOUR_BUCKET_NAME` (must be globally unique across all AWS accounts).
   - **AWS Region**: Select your target region (e.g., `us-east-1` or `ap-south-1`).
   - **Block Public Access**: Keep **"Block all public access" ENABLED (Checked)**.
   - **Default Encryption**: **Server-side encryption with Amazon S3 managed keys (SSE-S3 / AES256)**.
   - **Bucket Key**: Enabled.
3. Click **Create bucket**.
4. Open the newly created bucket, click the **Permissions** tab:
   - Scroll down to **Bucket Policy** and click **Edit**.
   - Copy the contents of `deploy/s3-bucket-policy.json`.
   - Replace `YOUR_BUCKET_NAME` with your actual bucket name.
   - Click **Save changes**.

---

### Step 2: Create the IAM Role for EC2
1. Open the [AWS IAM Console](https://console.aws.amazon.com/iam/).
2. Under **Access management**, select **Policies** -> **Create policy**:
   - Choose the **JSON** editor.
   - Paste the contents of `deploy/iam-policy.json`.
   - Replace `YOUR_BUCKET_NAME` with your actual bucket name.
   - Click **Next**. Name the policy: `FoodiesEC2S3CloudWatchPolicy`.
   - Click **Create policy**.
3. Under **Access management**, select **Roles** -> **Create role**:
   - **Trusted entity type**: AWS service.
   - **Use case**: EC2. Click **Next**.
   - **Permissions policies**: Search and attach `FoodiesEC2S3CloudWatchPolicy`.
   - *(Optional but recommended)* Also search and attach the AWS managed policy `CloudWatchAgentServerPolicy`.
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

### Step 7: Bootstrap the Ubuntu 24.04 Host
1. Connect to the EC2 instance via SSH:
   ```bash
   chmod 400 your-key.pem
   ssh -i your-key.pem ubuntu@<ELASTIC_IP>
   ```

2. Download and run the automated bootstrap script:
   ```bash
   # Download or copy bootstrap.sh
   sudo bash /opt/foodies/deploy/scripts/bootstrap.sh || curl -sSL https://raw.githubusercontent.com/omthorat986/food-static/main/deploy/scripts/bootstrap.sh | sudo bash
   ```
   *What this script does:*
   - Creates system group and user `foodies:foodies`.
   - Creates `/opt/foodies` (mode 750, `foodies:foodies`).
   - Creates `/var/lib/foodies` (mode 750, `foodies:foodies`).
   - Creates `/var/log/foodies` (mode 750, `foodies:foodies`).
   - Creates `/etc/foodies` (mode 750, `root:foodies`).
   - Creates ACME webroot directory `/var/www/certbot` (mode 755, `www-data:www-data`).
   - Adds `www-data` to the `foodies` group.
   - Adds CloudWatch agent user (`cwagent`) to the `foodies` and `adm` groups.
   - Initializes Python virtual environment at `/opt/foodies/venv`.

---

### Step 8: Clone Application Code with Read-Only Deploy Key
1. Generate a dedicated read-only SSH deploy key on the server:
   ```bash
   ssh-keygen -t ed25519 -C "foodies-deploy-key" -f ~/.ssh/id_ed25519_deploy -N ""
   cat ~/.ssh/id_ed25519_deploy.pub
   ```
2. Go to your GitHub repository -> **Settings** -> **Deploy keys** -> **Add deploy key**:
   - Title: `EC2-Production-ReadOnly`.
   - Paste the public key. Leave **"Allow write access" UNCHECKED**. Click **Add key**.

3. Clone the repository into `/opt/foodies`:
   ```bash
   sudo GIT_SSH_COMMAND="ssh -i /home/ubuntu/.ssh/id_ed25519_deploy -o IdentitiesOnly=yes" \
       git clone git@github.com:omthorat986/food-static.git /opt/foodies

   # Set ownership and permissions
   sudo chown -R foodies:foodies /opt/foodies
   sudo chmod 750 /opt/foodies
   ```

4. Install pinned Python dependencies:
   ```bash
   sudo /opt/foodies/venv/bin/pip install --no-cache-dir -r /opt/foodies/requirements.txt
   ```

---

### Step 9: Configure Production Environment Secrets
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
   S3_BUCKET=YOUR_BUCKET_NAME
   AWS_REGION=us-east-1
   DATABASE_PATH=/var/lib/foodies/foodies.db
   COOKIE_SECURE=true
   ALLOWED_HOSTS=my-foodies.duckdns.org,localhost,127.0.0.1
   ```

---

### Step 10: Run Database Migration and Create Admin Account
1. Apply database schema migrations idempotently:
   ```bash
   sudo -u foodies /opt/foodies/venv/bin/python /opt/foodies/manage.py migrate
   ```

2. Create the production administrator account (prompts with `getpass`, enforces 10+ characters):
   ```bash
   sudo -u foodies /opt/foodies/venv/bin/python /opt/foodies/manage.py create-admin
   ```
   Enter the admin email and a strong password (at least 10 characters).

---

### Step 11: Configure HTTP-Only Nginx (Starts Cleanly Before Certificates)
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
   sudo nginx -t
   sudo systemctl restart nginx
   ```
   *Verification:* Nginx starts cleanly on port 80 without SSL errors.

---

### Step 12: Obtain TLS Certificate via Certbot Webroot
Run Certbot in **webroot mode** targeting `/var/www/certbot`.
> [!IMPORTANT]
> Use `--webroot -w /var/www/certbot`, **NOT `--standalone`**! Webroot mode allows Let's Encrypt to verify domain ownership while Nginx remains active, enabling seamless automated renewals without downtime.

```bash
sudo certbot certonly \
    --webroot \
    -w /var/www/certbot \
    -d my-foodies.duckdns.org \
    --agree-tos \
    --no-eff-email \
    -m your-email@example.com
```

Test automated renewal:
```bash
sudo certbot renew --dry-run
```

---

### Step 13: Enable Full HTTPS Nginx Block & Start Systemd Service
1. Enable the production HTTPS Nginx configuration:
   ```bash
   sudo cp /opt/foodies/deploy/nginx-https.conf /etc/nginx/sites-available/foodies.conf
   sudo sed -i 's/YOUR_DOMAIN_NAME/my-foodies.duckdns.org/g' /etc/nginx/sites-available/foodies.conf
   sudo nginx -t
   sudo systemctl reload nginx
   ```

2. Install and start the Gunicorn systemd service:
   ```bash
   sudo cp /opt/foodies/deploy/foodies.service /etc/systemd/system/foodies.service
   sudo systemctl daemon-reload
   sudo systemctl enable --now foodies.service
   sudo systemctl status foodies.service
   ```

---

### Step 14: Install and Start AWS CloudWatch Agent
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

### Step 15: Setup CloudWatch Alarms & SNS Alerting
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

### Step 16: Execute Automated Post-Deployment Smoke Test
Run the automated verification script:
```bash
sudo bash /opt/foodies/deploy/scripts/smoke-test.sh my-foodies.duckdns.org YOUR_BUCKET_NAME us-east-1
```
*The smoke test validates:*
1. `GET /health` returns 200 OK and `status: "ok"`.
2. `GET /ready` returns 200 OK and `database: "ok"`.
3. HTTP to HTTPS 301 redirection works.
4. Security headers are present on all responses (`X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`, `Referrer-Policy`, `Permissions-Policy`, `Strict-Transport-Security`, CSP without inline scripts).
5. Information leakage prevention: sensitive paths (`/app.py`, `/foodies.db`, `/.env`, `/logs/app.log`, `/requirements.txt`, `/.git/config`, `/deploy/nginx.conf`) all return **404 Not Found**.
6. Private S3 isolation: raw direct object URL returns **403 AccessDenied**.

---

### Step 17: Setup Automated SQLite Backups
Set up a daily automated backup of the SQLite database using SQLite's online `.backup` command (locks safe):
```bash
sudo mkdir -p /var/lib/foodies/backups
sudo chown foodies:foodies /var/lib/foodies/backups
sudo chmod 750 /var/lib/foodies/backups

# Add cron job to backup daily at 03:00 AM
echo '0 3 * * * foodies sqlite3 /var/lib/foodies/foodies.db ".backup '\''/var/lib/foodies/backups/foodies-$(date +\%F).db'\''" && find /var/lib/foodies/backups/ -name "foodies-*.db" -mtime +14 -delete' | sudo tee /etc/cron.d/foodies-backup
```

---

### Step 18: Security Cleanup
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
