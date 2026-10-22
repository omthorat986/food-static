#!/usr/bin/env bash
# =============================================================================
# Foodies AWS Post-Deployment Smoke Test Script
# =============================================================================
# Validates live deployment health, readiness, TLS redirect, security headers,
# information leakage prevention (404 on sensitive files), and S3 private bucket isolation.
#
# Usage:
#   ./smoke-test.sh [TARGET_DOMAIN] [S3_BUCKET_NAME] [AWS_REGION]
# Example:
#   ./smoke-test.sh foodies.duckdns.org my-foodies-bucket us-east-1

set -uo pipefail

TARGET_DOMAIN="${1:-${HOST:-localhost}}"
S3_BUCKET="${2:-${S3_BUCKET:-}}"
AWS_REGION="${3:-${AWS_REGION:-us-east-1}}"

SCHEME="https"

if [ "$TARGET_DOMAIN" = "localhost" ] || [ "$TARGET_DOMAIN" = "127.0.0.1" ]; then
    SCHEME="http"
    BASE_URL="http://${TARGET_DOMAIN}:8080"
else
    BASE_URL="https://${TARGET_DOMAIN}"
fi

echo "===================================================================="
echo " Foodies Post-Deployment Smoke Test Runner"
echo " Target Domain: ${TARGET_DOMAIN}"
echo " Base URL:      ${BASE_URL}"
echo "===================================================================="

PASSED_COUNT=0
FAILED_COUNT=0

record_result() {
    local check_name="$1"
    local expected="$2"
    local actual="$3"
    local status="$4"

    if [ "$status" = "PASS" ]; then
        echo -e "[\e[32mPASS\e[0m] ${check_name}: expected '${expected}', got '${actual}'"
        ((PASSED_COUNT++)) || true
    else
        echo -e "[\e[31mFAIL\e[0m] ${check_name}: expected '${expected}', got '${actual}'"
        ((FAILED_COUNT++)) || true
    fi
}

# 1. Health check (/health)
echo -e "\n--- [1] Checking Liveness Endpoint (/health) ---"
HEALTH_CODE=$(curl -s -k -o /dev/null -w "%{http_code}" "${BASE_URL}/health" || echo "000")
HEALTH_BODY=$(curl -s -k "${BASE_URL}/health" || echo "")
if [ "$HEALTH_CODE" = "200" ] && echo "$HEALTH_BODY" | grep -q '"status":\s*"ok"'; then
    record_result "Liveness probe (/health)" "200 OK & status='ok'" "${HEALTH_CODE}" "PASS"
else
    record_result "Liveness probe (/health)" "200 OK & status='ok'" "${HEALTH_CODE} (${HEALTH_BODY})" "FAIL"
fi

# 2. Readiness probe (/ready)
echo -e "\n--- [2] Checking Readiness Endpoint (/ready) ---"
READY_CODE=$(curl -s -k -o /dev/null -w "%{http_code}" "${BASE_URL}/ready" || echo "000")
READY_BODY=$(curl -s -k "${BASE_URL}/ready" || echo "")
if [ "$READY_CODE" = "200" ] && echo "$READY_BODY" | grep -q '"database":\s*"ok"'; then
    record_result "Readiness probe (/ready)" "200 OK & database='ok'" "${READY_CODE}" "PASS"
else
    record_result "Readiness probe (/ready)" "200 OK & database='ok'" "${READY_CODE} (${READY_BODY})" "FAIL"
fi

# 3. HTTP to HTTPS redirect
if [ "$SCHEME" = "https" ]; then
    echo -e "\n--- [3] Checking HTTP -> HTTPS 301 Redirect ---"
    HTTP_REDIRECT_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://${TARGET_DOMAIN}/" || echo "000")
    HTTP_LOCATION=$(curl -s -I "http://${TARGET_DOMAIN}/" | grep -i "^location:" | tr -d '\r\n' || echo "")
    if [ "$HTTP_REDIRECT_CODE" = "301" ] && echo "$HTTP_LOCATION" | grep -q "https://"; then
        record_result "HTTP -> HTTPS redirect" "301 Redirect to https://" "${HTTP_REDIRECT_CODE} (${HTTP_LOCATION})" "PASS"
    else
        record_result "HTTP -> HTTPS redirect" "301 Redirect to https://" "${HTTP_REDIRECT_CODE} (${HTTP_LOCATION})" "FAIL"
    fi
else
    echo -e "\n--- [3] Skipping HTTPS redirect check (Localhost Testing Mode) ---"
fi

# 4. Security Headers Verification
echo -e "\n--- [4] Verifying Security Headers ---"
HEADERS=$(curl -s -k -I "${BASE_URL}/health")

# X-Content-Type-Options: nosniff
if echo "$HEADERS" | grep -iq "X-Content-Type-Options:.*nosniff"; then
    record_result "Header: X-Content-Type-Options" "nosniff" "nosniff" "PASS"
else
    record_result "Header: X-Content-Type-Options" "nosniff" "Missing or incorrect" "FAIL"
fi

# X-Frame-Options: SAMEORIGIN
if echo "$HEADERS" | grep -iq "X-Frame-Options:.*SAMEORIGIN"; then
    record_result "Header: X-Frame-Options" "SAMEORIGIN" "SAMEORIGIN" "PASS"
else
    record_result "Header: X-Frame-Options" "SAMEORIGIN" "Missing or incorrect" "FAIL"
fi

# Referrer-Policy
if echo "$HEADERS" | grep -iq "Referrer-Policy:.*strict-origin"; then
    record_result "Header: Referrer-Policy" "strict-origin-when-cross-origin" "Present" "PASS"
else
    record_result "Header: Referrer-Policy" "strict-origin-when-cross-origin" "Missing" "FAIL"
fi

# Permissions-Policy
if echo "$HEADERS" | grep -iq "Permissions-Policy:"; then
    record_result "Header: Permissions-Policy" "geolocation=()..." "Present" "PASS"
else
    record_result "Header: Permissions-Policy" "geolocation=()..." "Missing" "FAIL"
fi

# Content-Security-Policy (without inline scripts)
if echo "$HEADERS" | grep -iq "Content-Security-Policy:"; then
    CSP_LINE=$(echo "$HEADERS" | grep -i "Content-Security-Policy:")
    if echo "$CSP_LINE" | grep -q "script-src 'self'" && ! echo "$CSP_LINE" | grep -q "'unsafe-inline';"; then
        record_result "Header: Content-Security-Policy" "script-src 'self' (no unsafe-inline)" "Strict CSP Enforced" "PASS"
    else
        record_result "Header: Content-Security-Policy" "script-src 'self' (no unsafe-inline)" "${CSP_LINE}" "FAIL"
    fi
else
    record_result "Header: Content-Security-Policy" "Present" "Missing" "FAIL"
fi

# Strict-Transport-Security (HTTPS only)
if [ "$SCHEME" = "https" ]; then
    if echo "$HEADERS" | grep -iq "Strict-Transport-Security:"; then
        record_result "Header: Strict-Transport-Security" "max-age=31536000" "Present" "PASS"
    else
        record_result "Header: Strict-Transport-Security" "max-age=31536000" "Missing" "FAIL"
    fi
fi

# 5. Information Leakage Prevention: Sensitive Paths Must Return 404
echo -e "\n--- [5] Information Leakage Prevention (Expect 404) ---"
SENSITIVE_PATHS=(
    "/app.py"
    "/foodies.db"
    "/requirements.txt"
    "/logs/app.log"
    "/.env"
    "/.git/config"
    "/deploy/nginx.conf"
)

for path in "${SENSITIVE_PATHS[@]}"; do
    STATUS=$(curl -s -k -o /dev/null -w "%{http_code}" "${BASE_URL}${path}")
    if [ "$STATUS" = "404" ]; then
        record_result "Path Protection (${path})" "404 Not Found" "${STATUS}" "PASS"
    else
        record_result "Path Protection (${path})" "404 Not Found" "${STATUS} (LEAKAGE DETECTED)" "FAIL"
    fi
done

# 6. S3 Bucket Public Access Block Verification
echo -e "\n--- [6] S3 Bucket Private Isolation Check ---"
if [ -n "$S3_BUCKET" ] && [ "$S3_BUCKET" != "YOUR_BUCKET_NAME" ]; then
    S3_URL="https://${S3_BUCKET}.s3.${AWS_REGION}.amazonaws.com/uploads/smoke-test.jpg"
    S3_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$S3_URL" || echo "000")
    if [ "$S3_CODE" = "403" ]; then
        record_result "Direct Public S3 Access (${S3_URL})" "403 AccessDenied (Bucket Private)" "${S3_CODE}" "PASS"
    else
        record_result "Direct Public S3 Access (${S3_URL})" "403 AccessDenied" "${S3_CODE} (BUCKET MAY BE PUBLIC)" "FAIL"
    fi
else
    echo "Notice: S3_BUCKET not specified or set to placeholder; skipping direct S3 URL probe."
fi

# Summary
echo -e "\n===================================================================="
echo " Smoke Test Summary: ${PASSED_COUNT} passed, ${FAILED_COUNT} failed"
echo "===================================================================="

if [ "$FAILED_COUNT" -eq 0 ]; then
    echo -e "RESULT: \e[32mALL SMOKE TESTS PASSED SUCCESSFULLY!\e[0m\n"
    exit 0
else
    echo -e "RESULT: \e[31mSMOKE TESTS FAILED!\e[0m\n"
    exit 1
fi
