#!/usr/bin/env python3
"""
Create Quick Suite user with OIDC federation for a given Cognito user email.
Usage: python create_quicksuite_user.py <email> --profile PROFILE
"""

import sys
import json
import boto3
import os
import re
import argparse
import logging
from botocore.exceptions import ClientError

# Suppress boto3/botocore logging
logging.getLogger('boto3').setLevel(logging.CRITICAL)
logging.getLogger('botocore').setLevel(logging.CRITICAL)
logging.getLogger('urllib3').setLevel(logging.CRITICAL)

# Module-level clients for reuse
cognito_client = None
quicksight_client = None
sts_client = None


def get_cognito_user_uuid(user_pool_id, email, region, profile):
    """Get Cognito user UUID by email with pagination support"""
    session = boto3.Session(profile_name=profile, region_name=region)
    cognito_client = session.client('cognito-idp')
    
    try:
        paginator = cognito_client.get_paginator('list_users')
        
        for page in paginator.paginate(UserPoolId=user_pool_id):
            for user in page['Users']:
                for attr in user['Attributes']:
                    if attr['Name'] == 'email' and attr['Value'] == email:
                        return user['Username']
        
        print(f"❌ User with email {email} not found in Cognito User Pool {user_pool_id}")
        return None
        
    except ClientError as e:
        print(f"❌ Error listing Cognito users: {e}")
        return None

def create_quicksight_user(email, external_login_id, account_id, web_identity_role_arn, user_pool_id, qs_region, profile, portal_url):
    """Create Quick Suite user with OIDC federation"""
    # Use QuickSight identity region for API calls
    session = boto3.Session(profile_name=profile, region_name=qs_region)
    quicksight_client = session.client('quicksight')
    
    # Extract AWS region from User Pool ID (format: us-east-1_XXXXXXXXX)
    if '_' not in user_pool_id:
        raise ValueError("Invalid User Pool ID format")
    aws_region = user_pool_id.split('_')[0]
    
    # Extract username from email for session name with validation
    if '@' not in email:
        raise ValueError("Invalid email format")
    username = email.split('@')[0]
    
    # Validate username for Quick Suite compatibility
    if not re.match(r'^[a-zA-Z0-9_-]+$', username):
        raise ValueError("Username contains invalid characters")
    
    try:
        response = quicksight_client.register_user(
            AwsAccountId=account_id,
            Namespace='default',
            Email=email,
            UserRole='READER_PRO',
            IdentityType='IAM',
            IamArn=web_identity_role_arn,
            SessionName=username,
            ExternalLoginFederationProviderType='CUSTOM_OIDC',
            CustomFederationProviderUrl=f'https://cognito-idp.{aws_region}.amazonaws.com/{user_pool_id}',
            ExternalLoginId=external_login_id
        )
        
        # Validate response
        if 'User' not in response:
            raise ValueError("Invalid response from Quick Suite API")
        
        status_msg = "✅ Created" if response.get('Status') == 201 else "✅ Updated"
        print(f"\n{status_msg} Quick Suite federated username: {response['User']['UserName']}")
        print(f"📧 Email: {email}")
        print(f"\n📋 Next Steps:")
        print(f"   1. Share Quick Suite Chat agents with this user in Quick Suite console")
        print(f"   2. User can sign in with the Email and temporary password (sent to the email) to the Portal {portal_url} and use the Chat agents that were shared with the user")
        
        return response
        
    except ClientError as e:
        if e.response['Error']['Code'] == 'ResourceExistsException':
            print(f"⚠️  Quick Suite user '{username}' already exists in the system")
            print(f"💡 Use 'aws quicksight describe-user' to view existing user details")
        else:
            print(f"❌ Failed to create Quick Suite user: {e}")
            print(f"💡 Check AWS permissions and Quick Suite subscription status")
        return None

def load_cdk_outputs():
    """Load CDK outputs from cdk-outputs.json"""
    import os
    
    # Try multiple locations for cdk-outputs.json
    possible_paths = [
        'cdk-outputs.json',  # Current directory
        'webapp/cdk-outputs.json',  # From project root
        '../webapp/cdk-outputs.json'  # From deployment/ directory
    ]
    
    for path in possible_paths:
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    outputs = json.load(f)
                # Get the first (and should be only) stack's outputs
                stack_name = list(outputs.keys())[0]
                return outputs[stack_name]
            except (json.JSONDecodeError, KeyError, IndexError) as e:
                print(f"❌ Error reading {path}: {e}")
                continue
    
    print("❌ cdk-outputs.json not found. Run 'cdk deploy --outputs-file cdk-outputs.json' first.")
    return None

def main():
    parser = argparse.ArgumentParser(description='Create QuickSuite user with OIDC federation')
    parser.add_argument('email', help='User email address')
    parser.add_argument('--profile', help='AWS profile name', required=True)
    args = parser.parse_args()
    
    email = args.email
    
    # Validate email format with stronger regex
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(email_pattern, email):
        print("❌ Invalid email format")
        sys.exit(1)
    
    # Load CDK outputs
    cdk_outputs = load_cdk_outputs()
    if not cdk_outputs:
        sys.exit(1)
    
    # Always use region from CDK outputs, never from profile
    region = cdk_outputs.get('Region')
    
    if not region:
        print("❌ Region not found in CDK outputs")
        sys.exit(1)
    
    # Get AWS account ID using explicit profile and region
    try:
        session = boto3.Session(profile_name=args.profile, region_name=region)
        sts_client = session.client('sts')
        account_id = sts_client.get_caller_identity()['Account']
    except ClientError as e:
        print(f"❌ Error getting AWS account ID: {e}")
        sys.exit(1)
    
    # Extract values from CDK outputs with validation
    try:
        user_pool_id = cdk_outputs['CognitoUserPoolId']
        web_identity_role_arn = cdk_outputs['WebIdentityRoleArn']
        qs_region = cdk_outputs['QuickSightIdentityRegion']  # QuickSight identity region
        portal_url = cdk_outputs['CloudFrontURL']
        
        # Validate extracted values
        if not user_pool_id or not re.match(r'^[a-zA-Z0-9-]+_[A-Za-z0-9]+$', user_pool_id):
            raise ValueError("Invalid User Pool ID format")
        if not web_identity_role_arn or not web_identity_role_arn.startswith('arn:aws:iam:'):
            raise ValueError("Invalid Role ARN format")
            
    except KeyError as e:
        print(f"❌ Missing required key in CDK outputs: {e}")
        print("💡 Ensure CDK stack was deployed successfully")
        sys.exit(1)
    
    # Get Cognito user UUID
    external_login_id = get_cognito_user_uuid(user_pool_id, email, region, args.profile)
    if not external_login_id:
        sys.exit(1)
    
    # Create Quick Suite user
    create_quicksight_user(email, external_login_id, account_id, web_identity_role_arn, user_pool_id, qs_region, args.profile, portal_url)

if __name__ == "__main__":
    main()