#!/bin/bash
# Script to inject CDK outputs into frontend config.js

set -e

# Check for required dependencies
command -v jq >/dev/null 2>&1 || { echo "❌ jq is required but not installed. Install with: brew install jq (macOS) or apt-get install jq (Linux)"; exit 1; }

if [ ! -f "webapp/cdk-outputs.json" ]; then
    echo "❌ cdk-outputs.json not found. Run 'cd webapp && cdk deploy' first."
    exit 1
fi

STACK_ID=$(jq -r 'keys[0]' webapp/cdk-outputs.json)
COGNITO_DOMAIN_URL=$(jq -r ".[\"$STACK_ID\"].CognitoDomainUrl" webapp/cdk-outputs.json)
COGNITO_CLIENT_ID=$(jq -r ".[\"$STACK_ID\"].CognitoClientId" webapp/cdk-outputs.json)
API_URL=$(jq -r ".[\"$STACK_ID\"].ApiGatewayURL" webapp/cdk-outputs.json)
CLOUDFRONT_URL=$(jq -r ".[\"$STACK_ID\"].CloudFrontURL" webapp/cdk-outputs.json)
PORTAL_TITLE=$(jq -r ".[\"$STACK_ID\"].PortalTitle" webapp/cdk-outputs.json)

# Validate extracted values
if [ -z "$STACK_ID" ] || [ "$STACK_ID" = "null" ]; then
    echo "❌ Failed to extract STACK_ID from CDK outputs"
    exit 1
fi

if [ -z "$COGNITO_DOMAIN_URL" ] || [ "$COGNITO_DOMAIN_URL" = "null" ]; then
    echo "❌ Failed to extract COGNITO_DOMAIN_URL from CDK outputs"
    exit 1
fi

if [ -z "$COGNITO_CLIENT_ID" ] || [ "$COGNITO_CLIENT_ID" = "null" ]; then
    echo "❌ Failed to extract COGNITO_CLIENT_ID from CDK outputs"
    exit 1
fi

if [ -z "$API_URL" ] || [ "$API_URL" = "null" ]; then
    echo "❌ Failed to extract API_URL from CDK outputs"
    exit 1
fi

if [ -z "$CLOUDFRONT_URL" ] || [ "$CLOUDFRONT_URL" = "null" ]; then
    echo "❌ Failed to extract CLOUDFRONT_URL from CDK outputs"
    exit 1
fi

if [ -z "$PORTAL_TITLE" ] || [ "$PORTAL_TITLE" = "null" ]; then
    echo "❌ Failed to extract PORTAL_TITLE from CDK outputs"
    exit 1
fi

echo "📝 Injecting configuration into my-app/dist/config.js..."

if [ ! -d "my-app/dist" ]; then
    echo "❌ my-app/dist not found. Run 'cd my-app && npm run build' first."
    exit 1
fi

# Escape special characters for JavaScript
escape_js() {
    printf '%s' "$1" | sed "s/\\\\/\\\\\\\\/g; s/'/\\\\'/g; s/\"/\\\\\"/g; s/\r/\\\\r/g; s/\n/\\\\n/g; s/\t/\\\\t/g"
}

COGNITO_DOMAIN_URL_ESC=$(escape_js "$COGNITO_DOMAIN_URL")
COGNITO_CLIENT_ID_ESC=$(escape_js "$COGNITO_CLIENT_ID")
API_URL_ESC=$(escape_js "$API_URL")
CLOUDFRONT_URL_ESC=$(escape_js "$CLOUDFRONT_URL")
PORTAL_TITLE_ESC=$(escape_js "$PORTAL_TITLE")

cat > my-app/dist/config.js << EOF
// Configuration injected during deployment
window.APP_CONFIG = {
    cognitoDomainUrl: '${COGNITO_DOMAIN_URL_ESC}',
    cognitoClientId: '${COGNITO_CLIENT_ID_ESC}',
    apiUrl: '${API_URL_ESC}',
    redirectUri: '${CLOUDFRONT_URL_ESC}',
    portalTitle: '${PORTAL_TITLE_ESC}',
    chatConfig: {
        fixedAgentId: '${CHAT_AGENT_ID:-}',
        allowFileAttachments: false,
        showWebSearch: false,
        showBrandAttribution: false,
        showAgentKnowledgeBoundary: true,
        showUsagePolicy: true
    }
};
EOF

echo "✅ Configuration injected successfully"
echo "📋 CloudFront URL: ${CLOUDFRONT_URL}"
echo "📋 API URL: ${API_URL}"
