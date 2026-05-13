#!/bin/bash

# Export PATH to ensure AWS CLI is accessible
export PATH="/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin:$PATH"

echo "🧹 Cleaning up QuickChat Embedding Solution"

# Check prerequisites
command -v jq >/dev/null 2>&1 || { echo "❌ jq required"; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "❌ Python3 required"; exit 1; }
command -v aws >/dev/null 2>&1 || { echo "❌ AWS CLI required"; exit 1; }
command -v cdk >/dev/null 2>&1 || { echo "❌ AWS CDK CLI required"; exit 1; }

# Check if cdk-outputs.json exists or is empty
if [ ! -f "webapp/cdk-outputs.json" ] || [ ! -s "webapp/cdk-outputs.json" ] || [ "$(cat webapp/cdk-outputs.json)" = "{}" ]; then
    echo "❌ webapp/cdk-outputs.json not found or empty."
    echo "💡 Run './setup.sh' first to deploy the stack."
    exit 1
fi

set -e

echo "📋 Getting outputs before destroying stack..."

# Auto-detect stack ID from CDK outputs
STACK_ID=$(jq -r 'keys[0]' webapp/cdk-outputs.json)
if [ -z "$STACK_ID" ] || [ "$STACK_ID" = "null" ]; then
    echo "❌ Failed to detect stack ID from CDK outputs"
    exit 1
fi
echo "📦 Detected stack ID: $STACK_ID"

# Get region, portal title, and AWS profile from CDK outputs
REGION=$(jq -r ".$STACK_ID.Region" webapp/cdk-outputs.json)
PORTAL_TITLE=$(jq -r ".$STACK_ID.PortalTitle" webapp/cdk-outputs.json)
AWS_PROFILE=$(jq -r ".$STACK_ID.AWSProfile // \"default\"" webapp/cdk-outputs.json)

echo "📋 Using AWS profile: $AWS_PROFILE"
export AWS_PROFILE="$AWS_PROFILE"

# Get Web Identity Role name for QuickSight user matching
WEB_IDENTITY_ROLE_ARN=$(jq -r ".$STACK_ID.WebIdentityRoleArn" webapp/cdk-outputs.json)
if [ -z "$WEB_IDENTITY_ROLE_ARN" ] || [ "$WEB_IDENTITY_ROLE_ARN" = "null" ]; then
    echo "⚠️  Failed to get Web Identity Role ARN from CDK outputs"
    WEB_IDENTITY_ROLE_ARN=""
fi

USER_POOL_ID=$(jq -r ".$STACK_ID.CognitoUserPoolId" webapp/cdk-outputs.json)
if [ -z "$USER_POOL_ID" ] || [ "$USER_POOL_ID" = "null" ]; then
    echo "⚠️  Failed to get User Pool ID from CDK outputs"
    USER_POOL_ID=""
fi

echo "👥 Setting up Python environment..."
if [ -f "scripts/requirements.txt" ]; then
    rm -rf venv
    python3 -m venv venv --clear || { echo "❌ Failed to create virtual environment"; exit 1; }
    venv/bin/pip install -r scripts/requirements.txt > /dev/null 2>&1 || { echo "❌ Failed to install Python dependencies"; exit 1; }
fi

echo "📋 Scanning resources to be deleted..."
echo ""

# Count Cognito users
if [ -n "$USER_POOL_ID" ]; then
    COGNITO_USER_COUNT=$(aws cognito-idp list-users --user-pool-id "$USER_POOL_ID" --profile "$AWS_PROFILE" --query 'length(Users)' --output text 2>/dev/null || echo "0")
else
    COGNITO_USER_COUNT=0
fi

# List Cognito users
if [ "$COGNITO_USER_COUNT" -gt 0 ]; then
    echo "👥 Cognito Users ($COGNITO_USER_COUNT):"
    aws cognito-idp list-users --user-pool-id "$USER_POOL_ID" --profile "$AWS_PROFILE" --query 'Users[].{Email:Attributes[?Name==`email`].Value|[0],Status:UserStatus}' --output table 2>/dev/null || echo "   Unable to list users"
    echo ""
fi

# Count and list QuickSight users
venv/bin/python -c "
import boto3
import sys

try:
    role_arn = '$WEB_IDENTITY_ROLE_ARN'
    role_name = role_arn.split('/')[-1]
    
    cognito = boto3.client('cognito-idp')
    cognito_users = cognito.list_users(UserPoolId='$USER_POOL_ID')['Users']
    
    quicksight = boto3.client('quicksight')
    account_id = boto3.client('sts').get_caller_identity()['Account']
    qs_users = quicksight.list_users(AwsAccountId=account_id, Namespace='default')['UserList']
    
    matching_users = []
    for cognito_user in cognito_users:
        email = None
        for attr in cognito_user.get('Attributes', []):
            if attr['Name'] == 'email':
                email = attr['Value']
                break
        
        if email and '@' in email:
            user_part = email.split('@')[0]
            expected_qs_username = f'{role_name}/{user_part}'
            
            for qs_user in qs_users:
                if (qs_user.get('Email') == email and 
                    qs_user.get('UserName') == expected_qs_username):
                    matching_users.append(f'{email} ({expected_qs_username})')
                    break
    
    if matching_users:
        print(f'🔍 QuickSight Users ({len(matching_users)}):')
        for user in matching_users:
            print(f'   • {user}')
        print()
except Exception as e:
    print(f'⚠️  Unable to list QuickSight users: {e}', file=sys.stderr)
" 2>/dev/null

# List CDK stack resources
echo "🏗️  CDK Stack Resources:"
AWS_PAGER="" aws cloudformation describe-stack-resources --stack-name "$STACK_ID" --region "$REGION" --profile "$AWS_PROFILE" --query 'StackResources[].{Type:ResourceType,ID:PhysicalResourceId}' --output table 2>/dev/null || echo "   Unable to list stack resources"
echo ""

# Confirm cleanup
echo ""
echo "⚠️  WARNING: This will permanently delete all resources listed above!"
echo ""
read -r -p "Are you sure you want to proceed? (y/N): " CONFIRM
if [[ ! $CONFIRM =~ ^[Yy]$ ]]; then
    echo "❌ Cleanup cancelled"
    rm -rf venv
    exit 0
fi

echo ""
echo "🗑️  Starting deletion process..."
echo ""

echo "🔍 Deleting Amazon Quick Suite users..."
if [ -n "$WEB_IDENTITY_ROLE_ARN" ] && [ -n "$USER_POOL_ID" ]; then
    venv/bin/python -c "
import boto3
import json
import sys

try:
    # Get role name from ARN
    role_arn = '$WEB_IDENTITY_ROLE_ARN'
    role_name = role_arn.split('/')[-1]
    
    # Get Cognito users first
    cognito = boto3.client('cognito-idp')
    cognito_users = cognito.list_users(UserPoolId='$USER_POOL_ID')['Users']
    
    # Get QuickSight users
    quicksight = boto3.client('quicksight')
    account_id = boto3.client('sts').get_caller_identity()['Account']
    qs_users = quicksight.list_users(AwsAccountId=account_id, Namespace='default')['UserList']
    
    deleted_count = 0
    for cognito_user in cognito_users:
        email = None
        for attr in cognito_user.get('Attributes', []):
            if attr['Name'] == 'email':
                email = attr['Value']
                break
        
        if email and '@' in email:
            user_part = email.split('@')[0]
            expected_qs_username = f'{role_name}/{user_part}'
            
            # Find matching QuickSight user
            for qs_user in qs_users:
                if (qs_user.get('Email') == email and 
                    qs_user.get('UserName') == expected_qs_username):
                    try:
                        quicksight.delete_user(
                            AwsAccountId=account_id,
                            Namespace='default',
                            UserName=expected_qs_username
                        )
                        print(f'✅ Deleted QuickSight user: {email}')
                        deleted_count += 1
                    except Exception as e:
                        print(f'⚠️  Failed to delete QuickSight user {email}: {e}')
                    break
    
    print(f'🗑️  Deleted {deleted_count} Amazon Quick Suite users')
except Exception as e:
    print(f'⚠️  QuickSight user cleanup failed: {e}')" || echo "⚠️  QuickSight user deletion failed, continuing..."
else
    echo "⚠️  Skipping QuickSight user deletion (missing data in cdk-outputs.json)"
fi

echo "🏗️ Destroying infrastructure..."
if [ ! -d "webapp" ]; then
    echo "❌ webapp directory not found"
    exit 1
fi

# Set CDK environment variables
export AWS_DEFAULT_REGION="$REGION"
export AWS_REGION="$REGION"
export CDK_DEFAULT_REGION="$REGION"
export CDK_DEFAULT_ACCOUNT=$(aws sts get-caller-identity --region "$REGION" --profile "$AWS_PROFILE" --query Account --output text)

cd webapp
echo "🔄 Running CDK destroy for stack: $STACK_ID"
echo "📋 Using AWS region: $REGION"
echo "📋 Using AWS account: $CDK_DEFAULT_ACCOUNT"
echo "📝 Using portal title: $PORTAL_TITLE"

if ! CDK_DEFAULT_REGION="$REGION" CDK_DEFAULT_ACCOUNT="$CDK_DEFAULT_ACCOUNT" cdk destroy "$STACK_ID" --region "$REGION" --profile "$AWS_PROFILE" --context portalTitle="$PORTAL_TITLE" --context stackName="$STACK_ID" --force; then
    echo "❌ CDK destroy failed"
    exit 1
fi
cd ..

# Verify stack deletion
echo "🔍 Verifying stack deletion..."
sleep 3
if aws cloudformation describe-stacks --stack-name "$STACK_ID" --region "$REGION" --profile "$AWS_PROFILE" >/dev/null 2>&1; then
    STACK_STATUS=$(aws cloudformation describe-stacks --stack-name "$STACK_ID" --region "$REGION" --profile "$AWS_PROFILE" --query 'Stacks[0].StackStatus' --output text 2>/dev/null)
    if [ "$STACK_STATUS" = "DELETE_COMPLETE" ] || [ "$STACK_STATUS" = "DELETE_IN_PROGRESS" ]; then
        echo "✅ Stack deletion in progress or completed: $STACK_STATUS"
    else
        echo "⚠️  Warning: Stack still exists with status: $STACK_STATUS"
    fi
else
    echo "✅ Stack successfully deleted"
fi

# Cleanup virtual environment
rm -rf venv

# Remove CDK outputs file
if [ -f "webapp/cdk-outputs.json" ]; then
    rm -f webapp/cdk-outputs.json
    echo "🗑️  Removed CDK outputs file"
fi

echo ""
echo "✅ Cleanup complete!"
echo "🧹 Deleted resources:"
echo "   • CDK stack: $STACK_ID"
if [ "$COGNITO_USER_COUNT" -gt 0 ]; then
    echo "   • Cognito users: $COGNITO_USER_COUNT"
fi
echo "   • QuickSight users: (see deletion log above)"
echo "   • CloudFront distribution, S3 bucket, Lambda, API Gateway, WAF, IAM roles"