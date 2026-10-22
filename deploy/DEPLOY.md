# Foodies Cloud Deployment Guide (AWS EC2, S3, IAM, CloudWatch)

This runbook provides complete, end-to-end instructions for deploying the **Foodies** cloud computing mini project on AWS.

---

## Architecture Summary
- **Compute**: AWS EC2 `t3.micro` or `t2.micro` (AWS Free Tier) running Ubuntu 24.04 LTS.
- **Web Server / Reverse Proxy**: Nginx handling HTTPS termination, HTTP->HTTPS redirect, static file caching, and reverse proxying to Gunicorn.
- **Application Server**: Python 3 + Flask + Gunicorn managed by `systemd`.
- **Database**: SQLite (`foodies.db`) with user authentication, bcrypt hashing, and metadata.
- **Object Storage**: Private Amazon S3 bucket (`uploads/` prefix) with AES256 server-side encryption and short-lived presigned URLs.
- **Identity & Access Management (IAM)**: EC2 IAM Role with least-privilege policy (S3 uploads prefix only, no root keys).
- **Security & SSL**: Free TLS/HTTPS certificate via Let's Encrypt (Certbot) on a DuckDNS domain.
- **Monitoring & Observability**: Amazon CloudWatch Agent shipping application logs and Nginx logs, tracking CPU/Memory/Disk metrics, and an SNS email alert when CPU > 70%.

---

## Step 1: Create the Amazon S3 Bucket
1. Open the [AWS S3 Console](https://s3.console.aws.amazon.com/).
2. Click **Create bucket**:
   - **Bucket name**: `foodies-cloud-storage-<YOUR_NAME_OR_ROLL_NO>` (must be globally unique).
   - **AWS Region**: Select your nearest region (e.g. `us-east-1` or `ap-south-1`).
   - **Block Public Access**: Keep **"Block all public access" ENABLED (Checked)**.
   - **Bucket Versioning**: Optional (Disabled or Enabled).
   - **Default Encryption**: Server-side encryption with **Amazon S3 managed keys (SSE-S3 / AES256)**.
3. Click **Create bucket**.
4. Inside the bucket, navigate to the **Permissions** tab:
   - Scroll to **Bucket Policy** and click **Edit**.
   - Paste the contents of `deploy/s3-bucket-policy.json` (replacing `foodies-cloud-storage-bucket` with your actual bucket name).
   - Save changes.

---

## Step 2: Create the IAM Role for EC2
1. Open the [AWS IAM Console](https://console.aws.amazon.com/iam/).
2. Under **Access management**, click **Policies** -> **Create policy**:
   - Click the **JSON** tab.
   - Paste the contents of `deploy/iam-policy.json` (update the bucket ARN to match your bucket name).
   - Name the policy: `FoodiesEC2S3CloudWatchPolicy`.
   - Click **Create policy**.
3. Under **Access management**, click **Roles** -> **Create role**:
   - **Trusted entity type**: AWS service.
   - **Use case**: EC2.
   - **Add permissions**: Search and select `FoodiesEC2S3CloudWatchPolicy`.
   - **Role name**: `FoodiesEC2Role`.
   - Click **Create role**.

---

## Step 3: Launch the EC2 Instance & Configure Security Group
1. Open the [AWS EC2 Console](https://console.aws.amazon.com/ec2/).
2. Click **Launch Instance**:
   - **Name**: `foodies-production-vm`.
   - **OS Image (AMI)**: **Ubuntu Server 24.04 LTS (HVM)**, SSD Volume Type (Free tier eligible).
   - **Instance type**: `t3.micro` (or `t2.micro`).
   - **Key pair**: Create or select an existing SSH key pair (`.pem`).
3. Under **Network settings**, configure the **Security Group**:
   - Create security group: `foodies-web-sg`.
   - **Rule 1 (SSH)**: Port `22` | Source: **My IP** (never `0.0.0.0/0` for security).
   - **Rule 2 (HTTP)**: Port `80` | Source: `Anywhere (0.0.0.0/0)` (needed for ACME challenge & HTTPS redirect).
   - **Rule 3 (HTTPS)**: Port `443` | Source: `Anywhere (0.0.0.0/0)` (secure browser access).
4. Under **Advanced details**:
   - **IAM instance profile**: Select `FoodiesEC2Role` created in Step 2.
5. Click **Launch instance**.
6. Note your instance's **Public IPv4 Address**.

---

## Step 4: Setup Free Domain Name via DuckDNS
1. Visit [DuckDNS](https://www.duckdns.org/) and log in with GitHub/Google.
2. In the **domains** section, create a free subdomain: e.g. `foodies-<rollno>`.
3. In the **ip** field, enter your EC2 instance's **Public IPv4 address**.
4. Click **update ip**. Your domain will now resolve: `foodies-<rollno>.duckdns.org`.

---

## Step 5: Connect to the Instance & Deploy Application Code
1. Open a terminal and connect to your EC2 instance via SSH:
   ```bash
   chmod 400 your-key.pem
   ssh -i your-key.pem ubuntu@<EC2_PUBLIC_IP>
   ```

2. Update system packages and install required dependencies:
   ```bash
   sudo apt-get update && sudo apt-get upgrade -y
   sudo apt-get install -y python3-pip python3-venv nginx git certbot python3-certbot-nginx curl
   ```

3. Clone or copy your project into `/home/ubuntu/Foodies-Static`:
   ```bash
   cd /home/ubuntu
   git clone <YOUR_REPO_URL> Foodies-Static
   cd Foodies-Static
   ```

4. Create and activate a Python virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

5. Run the automated self-test to verify backend functionality:
   ```bash
   python app.py --test
   ```
   *(Ensure all 10 test cases report PASS)*.

---

## Step 6: Configure Systemd Service for Gunicorn
1. Copy the systemd service file:
   ```bash
   sudo cp deploy/foodies.service /etc/systemd/system/foodies.service
   ```

2. Edit the service file to set your actual bucket name, region, and secret key:
   ```bash
   sudo nano /etc/systemd/system/foodies.service
   ```
   Update:
   - `Environment="S3_BUCKET=<YOUR_ACTUAL_BUCKET_NAME>"`
   - `Environment="AWS_REGION=<YOUR_AWS_REGION>"`
   - `Environment="SECRET_KEY=<GENERATE_A_RANDOM_SECRET>"`

3. Reload systemd, enable, and start the service:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable foodies
   sudo systemctl start foodies
   sudo systemctl status foodies
   ```

4. Verify local application response:
   ```bash
   curl http://127.0.0.1:8080/health
   # Expected: {"region":"us-east-1","service":"foodies-cloud","status":"ok","storage_mode":"s3",...}
   ```

---

## Step 7: Configure Nginx & Obtain HTTPS SSL via Certbot
1. Configure Nginx virtual host:
   ```bash
   sudo cp deploy/nginx.conf /etc/nginx/sites-available/foodies.conf
   sudo nano /etc/nginx/sites-available/foodies.conf
   ```
   Replace `foodies.duckdns.org` with your actual DuckDNS domain name.

2. Enable the site and test configuration:
   ```bash
   sudo ln -sf /etc/nginx/sites-available/foodies.conf /etc/nginx/sites-enabled/
   sudo rm -f /etc/nginx/sites-enabled/default
   sudo nginx -t
   sudo systemctl restart nginx
   ```

3. Obtain Let's Encrypt SSL certificate:
   ```bash
   sudo certbot --nginx -d <YOUR_SUBDOMAIN>.duckdns.org --non-interactive --agree-tos -m <YOUR_EMAIL>
   ```

4. Verify Certbot automatically updated `/etc/nginx/sites-available/foodies.conf` with valid SSL cert directives. Reload Nginx:
   ```bash
   sudo systemctl reload nginx
   ```

5. Test in your browser: `https://<YOUR_SUBDOMAIN>.duckdns.org`. Look for the secure padlock icon!

---

## Step 8: Install and Configure Amazon CloudWatch Agent
1. Download and install the official CloudWatch agent on Ubuntu:
   ```bash
   wget https://amazoncloudwatch-agent.s3.amazonaws.com/ubuntu/amd64/latest/amazon-cloudwatch-agent.deb
   sudo dpkg -i -E ./amazon-cloudwatch-agent.deb
   ```

2. Copy the configuration file:
   ```bash
   sudo cp deploy/cloudwatch-agent-config.json /opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json
   ```

3. Start the CloudWatch agent:
   ```bash
   sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \
       -a fetch-config \
       -m ec2 \
       -s \
       -c file:/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json
   ```

4. Verify agent status:
   ```bash
   sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -m ec2 -a status
   # Expected: "status": "running"
   ```

---

## Step 9: Configure CloudWatch Dashboard, CPU Alarm & SNS Alerts
1. Open the [AWS CloudWatch Console](https://console.aws.amazon.com/cloudwatch/).
2. Under **Alarms**, click **Create alarm**:
   - Click **Select metric** -> `EC2` -> `Per-Instance Metrics`.
   - Select `CPUUtilization` for your instance (`foodies-production-vm`).
   - Statistic: **Average**, Period: **1 minute**.
   - Threshold condition: **Static**, **Greater than > 70**.
3. Click **Next** to configure notification actions:
   - Alarm state trigger: **In alarm**.
   - Select **Create new topic**: e.g. `foodies-cpu-alarm-topic`.
   - Email recipient: Enter your email address.
   - Click **Create topic**.
   - *(Check your email inbox and click the **Confirm subscription** link!)*
4. Name the alarm: `Foodies-High-CPU-Utilization-Alarm`.
5. Click **Create alarm**.

6. Create a CloudWatch Dashboard:
   - Go to **Dashboards** -> **Create dashboard** (`Foodies-Performance-Dashboard`).
   - Add widgets:
     - Line widget: `CPUUtilization` (EC2)
     - Line widget: `mem_used_percent` (Namespace `FoodiesCloudApp`)
     - Line widget: `disk_used_percent` (Namespace `FoodiesCloudApp`)
     - Log table widget: Query log group `/aws/ec2/foodies/app` for `AUDIT` events.

---

## Step 10: Clean-Up & Billing Alert (Avoid Unwanted Charges)

> [!WARNING]
> Always terminate resources or set billing alerts when the viva/demonstration is finished.

1. **Set a Zero-Spend / Free-Tier Billing Alert**:
   - Go to [AWS Billing & Cost Management](https://console.aws.amazon.com/billing/).
   - Click **Budgets** -> **Create budget**.
   - Choose **Cost budget (Recommended)**.
   - Budget amount: `$1.00` per month.
   - Configure alert email to notify you if forecasted spend exceeds 80% ($0.80).

2. **Temporarily Stop Resources (when not demoing)**:
   - In EC2 Console: Select `foodies-production-vm` -> **Instance state** -> **Stop instance** (stops compute billing; EBS volume retention is negligible).

3. **Permanently Tear Down / Terminate (after final viva grading)**:
   - **EC2**: Select instance -> **Instance state** -> **Terminate instance**.
   - **S3**: Open your S3 bucket -> Click **Empty** -> Type `permanently delete` -> Click **Delete bucket**.
   - **IAM**: Delete `FoodiesEC2Role` and `FoodiesEC2S3CloudWatchPolicy`.
   - **CloudWatch**: Delete alarms, dashboards, and log groups under `/aws/ec2/foodies/`.
   - **DuckDNS**: Delete or release your subdomain.
