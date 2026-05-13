#!/bin/bash
set -e

# Export PATH to ensure AWS CLI is accessible
export PATH="/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin:$PATH"

echo "🚀 Setting up QuickChat Embedding Solution"

# Check if this is an update or new deployment
if [ -f "webapp/cdk-outputs.json" ] && [ -s "webapp/cdk-outputs.json" ] && [ "$(jq 'keys | length' webapp/cdk-outputs.json 2>/dev/null)" != "0" ]; then
    echo "📋 Existing deployment detected - running update"
    UPDATE_MODE=true
else
    echo "📋 New deployment detected"
    UPDATE_MODE=false
fi

# Check prerequisites
command -v aws >/dev/null 2>&1 || { echo "❌ AWS CLI required"; exit 1; }
command -v npm >/dev/null 2>&1 || { echo "❌ Node.js/npm required"; exit 1; }
command -v jq >/dev/null 2>&1 || { echo "❌ jq required"; exit 1; }
docker info >/dev/null 2>&1 || { echo "❌ Docker required and must be running"; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "❌ Python3 required"; exit 1; }

# Set parameters
if [ "$UPDATE_MODE" = true ]; then
    # Load existing parameters from CDK outputs
    STACK_NAME=$(jq -r 'keys[0]' webapp/cdk-outputs.json)
    
    # Verify stack actually exists in CloudFormation
    AWS_PROFILE_TEMP=$(jq -r ".\"$STACK_NAME\".AWSProfile // \"default\"" webapp/cdk-outputs.json)
    DEPLOYMENT_AWS_REGION_TEMP=$(jq -r ".\"$STACK_NAME\".Region // \"us-east-1\"" webapp/cdk-outputs.json)
    
    if ! AWS_PROFILE=$AWS_PROFILE_TEMP aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$DEPLOYMENT_AWS_REGION_TEMP" >/dev/null 2>&1; then
        echo "⚠️  CDK outputs found but stack '$STACK_NAME' does not exist in CloudFormation"
        echo "📋 Starting fresh deployment"
        rm -f webapp/cdk-outputs.json
        UPDATE_MODE=false
    fi
fi

if [ "$UPDATE_MODE" = true ]; then
    PORTAL_TITLE=$(jq -r ".\"$STACK_NAME\".PortalTitle" webapp/cdk-outputs.json)
    DEPLOYMENT_AWS_REGION=$(jq -r ".\"$STACK_NAME\".Region" webapp/cdk-outputs.json)
    AWS_PROFILE=$(jq -r ".\"$STACK_NAME\".AWSProfile // \"default\"" webapp/cdk-outputs.json)
    echo "📋 Using existing Enter CloudFormation stack name: $STACK_NAME"
    echo "📋 Using existing portal title: $PORTAL_TITLE"
    echo "📋 Using existing AWS region: $DEPLOYMENT_AWS_REGION"
    echo "📋 Using existing AWS CLI profile: $AWS_PROFILE"
else
    # New deployment - prompt for all parameters
    read -r -p "Enter portal title (e.g. QuickChat Portal): " PORTAL_TITLE
    if [ -z "$PORTAL_TITLE" ]; then
        echo "❌ Portal title is required"
        exit 1
    fi
    
    read -r -p "Enter CloudFormation stack name (e.g. webapp123): " STACK_NAME
    if [ -z "$STACK_NAME" ]; then
        echo "❌ Stack ID is required"
        exit 1
    fi
    
    # Validate stack ID length immediately
    if [ ${#STACK_NAME} -gt 12 ]; then
        echo "❌ Stack ID must be 12 characters or less"
        exit 1
    fi
    
    read -r -p "Enter AWS region (e.g. us-east-1): " DEPLOYMENT_AWS_REGION
    if [ -z "$DEPLOYMENT_AWS_REGION" ]; then
        echo "❌ AWS region is required"
        exit 1
    fi
    # Remove any trailing whitespace or commas
    DEPLOYMENT_AWS_REGION=$(echo "$DEPLOYMENT_AWS_REGION" | tr -d '[:space:],' | tr '[:upper:]' '[:lower:]')
    
    # Validate AWS region format immediately
    if [[ ! "$DEPLOYMENT_AWS_REGION" =~ ^[a-z]{2}-[a-z]+-[0-9]+$ ]]; then
        echo "❌ Invalid AWS region format: $DEPLOYMENT_AWS_REGION"
        echo "   Expected format: us-east-1, us-west-2, eu-west-1, etc."
        exit 1
    fi
    
    read -r -p "Enter AWS CLI profile (e.g. default): " AWS_PROFILE
    if [ -z "$AWS_PROFILE" ]; then
        echo "❌ AWS CLI profile is required"
        exit 1
    fi
fi

echo ""
echo "📋 Deployment Summary:"
echo "   CloudFormation stack name: $STACK_NAME"
echo "   Portal Title: $PORTAL_TITLE"
echo "   AWS Region: $DEPLOYMENT_AWS_REGION"
echo "   AWS Profile: $AWS_PROFILE"
if [ "$UPDATE_MODE" = true ]; then
    echo "   Mode: UPDATE"
else
    echo "   Mode: NEW DEPLOYMENT"
fi
echo ""
read -r -p "Do you want to proceed with deployment? (y/N): " CONFIRM
if [[ ! $CONFIRM =~ ^[Yy]$ ]]; then
    echo "❌ Deployment cancelled"
    exit 0
fi

# Set AWS profile and CDK environment variables
export AWS_PROFILE="$AWS_PROFILE"
export AWS_DEFAULT_REGION="$DEPLOYMENT_AWS_REGION"
export AWS_REGION="$DEPLOYMENT_AWS_REGION"
export CDK_DEFAULT_REGION="$DEPLOYMENT_AWS_REGION"
export CDK_DEFAULT_ACCOUNT=$(aws sts get-caller-identity --region "$DEPLOYMENT_AWS_REGION" --profile "$AWS_PROFILE" --query Account --output text)

echo "📋 Using AWS Account: $CDK_DEFAULT_ACCOUNT"

# Get QuickSight identity region
echo "🔍 Detecting QuickSight identity region..."
QUICKSIGHT_IDENTITY_REGION=$(aws quicksight list-namespaces --aws-account-id "$CDK_DEFAULT_ACCOUNT" --profile "$AWS_PROFILE" 2>/dev/null | grep -m 1 '"Arn"' | sed -n 's/.*:quicksight:\([^:]*\):.*/\1/p')

if [ -z "$QUICKSIGHT_IDENTITY_REGION" ]; then
    echo "❌ Failed to detect QuickSight identity region. Ensure QuickSight is set up in your account."
    exit 1
fi

echo "📋 QuickSight Identity Region: $QUICKSIGHT_IDENTITY_REGION"
export QUICKSIGHT_IDENTITY_REGION

echo "🔐 Authenticating Docker with AWS ECR Public..."
if aws ecr-public get-login-password --region us-east-1 --profile "$AWS_PROFILE" 2>/dev/null | docker login --username AWS --password-stdin public.ecr.aws >/dev/null 2>&1; then
    echo "✅ Docker authenticated with ECR Public"
else
    echo "⚠️  Warning: Docker ECR authentication failed, but continuing..."
fi

echo "📦 Installing dependencies..."
if [ ! -d "webapp" ]; then
    echo "❌ webapp directory not found"
    exit 1
fi
cd webapp
npm install

echo "🏗️ Building TypeScript code..."
npm run build

echo "🏗️ Bootstrapping CDK..."
cdk bootstrap aws://$CDK_DEFAULT_ACCOUNT/$DEPLOYMENT_AWS_REGION

echo "📋 Validating CDK stack before deployment..."
cdk synth --context portalTitle="$PORTAL_TITLE" --context stackName="$STACK_NAME" --context quicksightIdentityRegion="$QUICKSIGHT_IDENTITY_REGION"
cdk diff --context portalTitle="$PORTAL_TITLE" --context stackName="$STACK_NAME" --context quicksightIdentityRegion="$QUICKSIGHT_IDENTITY_REGION"

echo "🔒 Running security validation..."
cd ..
if [ ! -x "./security-check.sh" ]; then
    echo "❌ Security check script not found or not executable"
    exit 1
fi
./security-check.sh "$STACK_NAME" "$PORTAL_TITLE"
echo "✅ Security validation passed"

# Create placeholder config.js for new deployments
if [ "$UPDATE_MODE" = false ]; then
    echo "📝 Creating placeholder config.js..."
    cat > frontend/config.js << 'EOF'
window.APP_CONFIG = {
    cognitoDomainUrl: '',
    cognitoClientId: '',
    apiUrl: '',
    redirectUri: '',
    portalTitle: 'Loading...',
    chatConfig: {}
};
EOF
fi

cd webapp

echo "🚀 Deploying infrastructure..."
CDK_DEFAULT_REGION="$DEPLOYMENT_AWS_REGION" CDK_DEFAULT_ACCOUNT="$CDK_DEFAULT_ACCOUNT" cdk deploy "$STACK_NAME" \
  --context portalTitle="$PORTAL_TITLE" \
  --context stackName="$STACK_NAME" \
  --context quicksightIdentityRegion="$QUICKSIGHT_IDENTITY_REGION" \
  --context dashboardId="${DASHBOARD_ID:-}" \
  --outputs-file cdk-outputs.json \
  --require-approval never

echo "📋 First-pass deploy complete. If DASHBOARD_ID was empty, re-run setup.sh after creating the dashboard."
echo "📋 Getting domain for Quick Suite allowlist..."
if [ ! -f "cdk-outputs.json" ]; then
    echo "❌ cdk-outputs.json not found"
    exit 1
fi
API_DOMAIN=$(jq -r --arg sid "$STACK_NAME" '.[$sid].ApiDomain' cdk-outputs.json)
CLOUDFRONT_DOMAIN=$(jq -r --arg sid "$STACK_NAME" '.[$sid].CloudFrontDomain' cdk-outputs.json)
if [ -z "$API_DOMAIN" ] || [ "$API_DOMAIN" = "null" ]; then
    echo "❌ Failed to extract API domain from CDK outputs"
    exit 1
fi
if [ -z "$CLOUDFRONT_DOMAIN" ] || [ "$CLOUDFRONT_DOMAIN" = "null" ]; then
    echo "❌ Failed to extract CloudFront domain from CDK outputs"
    exit 1
fi

echo "📝 Injecting configuration into frontend files..."
cd ..
if [ ! -x "./inject-config.sh" ]; then
    echo "❌ inject-config.sh script not found or not executable"
    exit 1
fi
./inject-config.sh

# Redeploy to update frontend with real config
echo "🔄 Redeploying to update frontend files..."
cd webapp
CDK_DEFAULT_REGION="$DEPLOYMENT_AWS_REGION" CDK_DEFAULT_ACCOUNT="$CDK_DEFAULT_ACCOUNT" cdk deploy "$STACK_NAME" \
  --context portalTitle="$PORTAL_TITLE" \
  --context stackName="$STACK_NAME" \
  --context quicksightIdentityRegion="$QUICKSIGHT_IDENTITY_REGION" \
  --context dashboardId="${DASHBOARD_ID:-}" \
  --outputs-file cdk-outputs.json \
  --require-approval never

echo "📋 Final outputs..."
WEBAPP_URL=$(jq -r --arg sid "$STACK_NAME" '.[$sid].CloudFrontURL' cdk-outputs.json)
if [ -z "$WEBAPP_URL" ] || [ "$WEBAPP_URL" = "null" ]; then
    echo "❌ Failed to get webapp URL from CDK outputs"
    exit 1
fi

echo ""
if [ "$UPDATE_MODE" = true ]; then
    echo "✅ Update complete!"
else
    echo "✅ Deployment complete!"
fi
echo ""
echo "📝 Next steps:"
echo "1. Create Cognito user"
echo "2. Create Quick Suite federated user"
echo "3. Share Quick Suite Chat agents with the federated user"
echo "4. Access web portal to use the Quick Suite Chat agents: $WEBAPP_URL"