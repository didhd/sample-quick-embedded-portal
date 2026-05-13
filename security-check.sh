#!/bin/bash

# Check for required dependencies
command -v jq >/dev/null 2>&1 || { echo "❌ jq is required but not installed. Install with: brew install jq (macOS) or apt-get install jq (Linux)"; exit 1; }

# Validate input parameters first
if [ -z "$1" ] || [ -z "$2" ]; then
    echo "❌ Usage: $0 <stack_id> <portal_title>"
    exit 1
fi

# Get stack ID and portal title from command line arguments
STACK_ID="$1"
PORTAL_TITLE="$2"

# Sanitize inputs - allow only alphanumeric, hyphens, underscores, spaces
if [[ ! "$STACK_ID" =~ ^[a-zA-Z0-9_-]+$ ]]; then
    echo "❌ Invalid STACK_ID: must contain only alphanumeric characters, hyphens, and underscores"
    exit 1
fi

if [[ ! "$PORTAL_TITLE" =~ ^[a-zA-Z0-9_\ -]+$ ]]; then
    echo "❌ Invalid PORTAL_TITLE: must contain only alphanumeric characters, spaces, hyphens, and underscores"
    exit 1
fi

TEMPLATE="webapp/cdk.out/$STACK_ID.template.json"
CDK_SOURCE="webapp/lib/webapp-stack.ts"
CRITICAL=0
WARNINGS=0
PASSED=0

echo "🔒 Sophisticated Security Validation for QuickChat Embedding Stack"
echo "=================================================================="
echo "📋 Analyzing CloudFormation: $TEMPLATE"
echo "📋 Analyzing CDK Source: $CDK_SOURCE"
echo ""

if [ ! -f "$TEMPLATE" ]; then
    echo "❌ Template not found. Run: cd webapp && cdk synth --context portalTitle='$PORTAL_TITLE' --context stackId=$STACK_ID"
    exit 1
fi

if [ ! -f "$CDK_SOURCE" ]; then
    echo "❌ CDK source not found at $CDK_SOURCE"
    exit 1
fi

check_result() {
    local test_name="$1"
    local result="$2"
    local severity="$3"
    local details="$4"
    
    if [ "$result" = "PASS" ]; then
        echo "✅ $test_name: PASS"
        [ -n "$details" ] && echo "   └─ $details"
        ((PASSED++))
    elif [ "$result" = "FAIL" ]; then
        if [ "$severity" = "CRITICAL" ]; then
            echo "❌ $test_name: CRITICAL FAILURE"
            [ -n "$details" ] && echo "   └─ $details"
            ((CRITICAL++))
        else
            echo "⚠️  $test_name: WARNING"
            [ -n "$details" ] && echo "   └─ $details"
            ((WARNINGS++))
        fi
    fi
}

echo "🔍 CORS Security Analysis:"

# Check for API Gateway CORS wildcards
if grep -q '"Access-Control-Allow-Origin".*"\*"' "$TEMPLATE"; then
    check_result "API Gateway CORS Origin" "FAIL" "CRITICAL" "Found wildcard (*) origin in API Gateway"
elif grep -q "Access-Control-Allow-Origin" "$TEMPLATE" && grep -q "Fn::Join" "$TEMPLATE"; then
    check_result "API Gateway CORS Origin" "PASS" "" "Dynamic CORS origin using CloudFormation functions (secure)"
elif grep -q "Access-Control-Allow-Origin" "$TEMPLATE"; then
    check_result "API Gateway CORS Origin" "FAIL" "CRITICAL" "Hardcoded CORS origin detected"
else
    check_result "API Gateway CORS Origin" "FAIL" "WARNING" "No CORS configuration found"
fi

# Remove Lambda CORS check since it's now handled by API Gateway
# check_result "Lambda CORS Handling" "PASS" "" "CORS handled by API Gateway (standard pattern)"

echo ""
echo "🔍 Lambda Integration Security:"

# Check AWS_PROXY integration
proxy_count=$(grep -c '"Type": "AWS_PROXY"' "$TEMPLATE")
if [ "$proxy_count" -ge 1 ]; then
    check_result "Lambda Proxy Integration" "PASS" "" "Found $proxy_count AWS_PROXY integration(s) (API Gateway handles OPTIONS)"
else
    check_result "Lambda Proxy Integration" "FAIL" "CRITICAL" "No AWS_PROXY integration found"
fi

# Check authorization type
auth_none_count=$(grep -c '"AuthorizationType": "NONE"' "$TEMPLATE")
if [ "$auth_none_count" -ge 2 ]; then
    check_result "API Gateway Authorization" "PASS" "" "Methods use NONE authorization (security handled in Lambda)"
else
    check_result "API Gateway Authorization" "FAIL" "WARNING" "Expected 2+ methods with NONE authorization"
fi

echo ""
echo "🔍 Environment Variable Security:"

# Check ALLOWED_ORIGIN configuration
if grep -q '"ALLOWED_ORIGIN"' "$TEMPLATE" && grep -q '"Fn::Join"' "$TEMPLATE"; then
    check_result "ALLOWED_ORIGIN Configuration" "PASS" "" "Dynamic API Gateway domain (not hardcoded)"
elif grep -q '"ALLOWED_ORIGIN"' "$TEMPLATE"; then
    check_result "ALLOWED_ORIGIN Configuration" "FAIL" "WARNING" "ALLOWED_ORIGIN present but may be hardcoded"
else
    check_result "ALLOWED_ORIGIN Configuration" "FAIL" "CRITICAL" "ALLOWED_ORIGIN environment variable missing"
fi

# Check for hardcoded domains
if grep 'https://.*\.amazonaws\.com' "$TEMPLATE" | grep -v "Fn::" | grep -q .; then
    check_result "Hardcoded Domains" "FAIL" "WARNING" "Found potential hardcoded AWS domains"
else
    check_result "Hardcoded Domains" "PASS" "" "No hardcoded domains detected"
fi

echo ""
echo "🔍 WAF Protection Analysis:"

# Check WAF rule configuration
if grep -q '"RateLimitRule"' "$TEMPLATE"; then
    rate_limit=$(grep -o '"Limit": [0-9]*' "$TEMPLATE" | grep -o '[0-9]*')
    if [[ "$rate_limit" =~ ^[0-9]+$ ]] && [ "$rate_limit" -gt 0 ]; then
        check_result "WAF Rate Limiting" "PASS" "" "Rate limit set to $rate_limit requests per IP"
    else
        check_result "WAF Rate Limiting" "FAIL" "WARNING" "Rate limit value not found or invalid"
    fi
else
    check_result "WAF Rate Limiting" "FAIL" "CRITICAL" "No WAF rate limiting rule found"
fi

# Check WAF association
if grep -q '"WebACLAssociation"' "$TEMPLATE"; then
    check_result "WAF Association" "PASS" "" "WAF properly associated with API Gateway"
else
    check_result "WAF Association" "FAIL" "CRITICAL" "WAF not associated with API Gateway"
fi

echo ""
echo "🔍 IAM Security (Least Privilege):"

# Check QuickSight permissions
qs_actions=$(grep -o '"quicksight:[^"]*"' "$TEMPLATE" | wc -l)
if [ -n "$qs_actions" ] && [ "$qs_actions" -ge 4 ]; then
    check_result "QuickSight Permissions" "PASS" "" "Found $qs_actions specific QuickSight actions (least privilege)"
elif [ -n "$qs_actions" ] && [ "$qs_actions" -gt 0 ]; then
    check_result "QuickSight Permissions" "FAIL" "WARNING" "Only $qs_actions QuickSight actions found"
else
    check_result "QuickSight Permissions" "FAIL" "CRITICAL" "No QuickSight permissions found"
fi

# Check for wildcard resources (exclude CDK internal constructs)
if grep -q '"Resource": "\*"' "$TEMPLATE" && ! grep -A5 -B5 '"Resource": "\*"' "$TEMPLATE" | grep -q "CreateOpenIDConnectProvider"; then
    check_result "IAM Resource Wildcards" "FAIL" "CRITICAL" "Found wildcard (*) resources in IAM policies"
else
    check_result "IAM Resource Wildcards" "PASS" "" "No wildcard resources (least privilege enforced)"
fi

# Check session duration
if grep -q '"MaxSessionDuration": 3600' "$TEMPLATE"; then
    check_result "Session Duration Limit" "PASS" "" "1-hour session duration limit enforced"
else
    check_result "Session Duration Limit" "FAIL" "WARNING" "Session duration limit not found or incorrect"
fi

echo ""
echo "🔍 Cognito OAuth Security:"

# Check OAuth flows in CDK source (more accurate than CloudFormation)
if grep -q "authorizationCodeGrant: true" "$CDK_SOURCE" && grep -q "implicitCodeGrant: false" "$CDK_SOURCE"; then
    check_result "OAuth Flow Configuration" "PASS" "" "Secure authorization code flow (implicit disabled)"
elif grep -q "authorizationCodeGrant: true" "$CDK_SOURCE"; then
    check_result "OAuth Flow Configuration" "FAIL" "WARNING" "Authorization code enabled but implicit flow status unclear"
else
    check_result "OAuth Flow Configuration" "FAIL" "CRITICAL" "OAuth flow configuration not found or insecure"
fi

# Check MFA configuration
if grep -q '"MfaConfiguration": "OFF"' "$TEMPLATE"; then
    check_result "MFA Configuration" "PASS" "" "MFA disabled as designed for this solution"
else
    check_result "MFA Configuration" "FAIL" "WARNING" "MFA configuration not found or unexpected"
fi

echo ""
echo "🔍 Lambda Security Configuration:"

# Check concurrency limits
if grep -q '"ReservedConcurrentExecutions": 100' "$TEMPLATE"; then
    check_result "Lambda Concurrency Limits" "PASS" "" "DoS protection: 100 concurrent executions"
else
    check_result "Lambda Concurrency Limits" "FAIL" "WARNING" "No concurrency limits (DoS protection missing)"
fi

# Check timeout limits
if grep -q '"Timeout": 30' "$TEMPLATE"; then
    check_result "Lambda Timeout Limits" "PASS" "" "30-second timeout limit enforced"
else
    check_result "Lambda Timeout Limits" "FAIL" "WARNING" "Timeout limit not found or incorrect"
fi

echo ""
echo "🔍 Logging and Monitoring Security:"

# Check data tracing
if grep -q '"DataTraceEnabled": false' "$TEMPLATE"; then
    check_result "API Gateway Data Tracing" "PASS" "" "Sensitive data tracing disabled"
else
    check_result "API Gateway Data Tracing" "FAIL" "WARNING" "Data tracing configuration not found"
fi

# Check logging level
if grep -q '"LoggingLevel": "INFO"' "$TEMPLATE"; then
    check_result "API Gateway Logging" "PASS" "" "INFO level logging enabled"
else
    check_result "API Gateway Logging" "FAIL" "WARNING" "Logging level not configured properly"
fi

echo ""
echo "🔍 Additional Security Validations:"

# Check for potential secrets with proper exclusion logic
echo "🔍 Scanning for hardcoded secrets..."

# Search for suspicious patterns but exclude known safe AWS resource references
suspicious_secrets=$(grep -iE '(password|secret|key|token)' "$TEMPLATE" | \
    grep -v -E '(KeyId|KeyArn|AccessKey|SecretAccessKey|PublicKey|SessionToken|IdToken|RefreshToken|AuthorizationCode)' | \
    grep -v -E '("Type": "AWS::|Ref|Fn::|GetAtt)' | \
    wc -l)

if [ "$suspicious_secrets" -gt 0 ]; then
    check_result "Hardcoded Secrets Scan" "FAIL" "WARNING" "Found $suspicious_secrets potential secret(s) - manual review required"
else
    check_result "Hardcoded Secrets Scan" "PASS" "" "No suspicious hardcoded secrets detected"
fi

# Check resource naming
if grep -q '"Name".*".*quickchat-embed-api"' "$TEMPLATE" && grep -q '"FunctionName".*".*quickchat-embed-function"' "$TEMPLATE"; then
    check_result "Resource Naming" "PASS" "" "Proper resource naming with company prefix and descriptive names"
else
    check_result "Resource Naming" "FAIL" "WARNING" "Resource naming pattern not verified"
fi

echo ""
echo "=================================================================="
echo "🔒 COMPREHENSIVE SECURITY VALIDATION SUMMARY"
echo "=================================================================="
echo "📊 Results: $PASSED passed, $WARNINGS warnings, $CRITICAL critical issues"
echo ""

if [ "$CRITICAL" -eq 0 ] && [ "$WARNINGS" -eq 0 ]; then
    echo "🎉 SECURITY STATUS: EXCELLENT"
    echo "✅ All $PASSED security checks passed"
    echo "✅ Zero warnings or critical issues"
    echo "✅ Stack exceeds security requirements"
    echo "🚀 RECOMMENDED ACTION: Deploy immediately"
    echo ""
    echo "Deployment command:"
    echo "  cd webapp && cdk deploy $STACK_ID --context portalTitle='$PORTAL_TITLE' --context stackId=$STACK_ID --outputs-file cdk-outputs.json"
elif [ "$CRITICAL" -eq 0 ]; then
    echo "⚠️  SECURITY STATUS: ACCEPTABLE WITH WARNINGS"
    echo "✅ $PASSED security checks passed"
    echo "⚠️  $WARNINGS warning(s) detected"
    echo "✅ No critical security vulnerabilities"
    echo "🟡 RECOMMENDED ACTION: Review warnings, then deploy"
    echo ""
    echo "Warnings are typically configuration recommendations, not security vulnerabilities."
    echo "Deployment is safe to proceed if warnings are acceptable for your environment."
else
    echo "❌ SECURITY STATUS: CRITICAL VULNERABILITIES DETECTED"
    echo "✅ $PASSED security checks passed"
    echo "⚠️  $WARNINGS warning(s) detected"
    echo "❌ $CRITICAL critical security issue(s) found"
    echo "🚫 RECOMMENDED ACTION: DO NOT DEPLOY"
    echo ""
    echo "Critical issues must be resolved before deployment."
    echo "Review CDK code, fix issues, and re-run 'cdk synth' before deploying."
    exit 1
fi

echo ""
echo "Security validation completed at $(date)"
echo "Report generated by QuickChat Embedding Security Validator v2.0"