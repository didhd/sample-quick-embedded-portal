#!/usr/bin/env python3
"""
Create Cognito user with Cognito-generated temporary password sent via email.
Usage: python create_cognito_user.py <email> --profile PROFILE
"""

import sys
import json
import re
import boto3
import argparse
import logging
from botocore.exceptions import ClientError

# Suppress boto3/botocore logging
logging.getLogger('boto3').setLevel(logging.CRITICAL)
logging.getLogger('botocore').setLevel(logging.CRITICAL)
logging.getLogger('urllib3').setLevel(logging.CRITICAL)

# Initialize boto3 client later with proper region
cognito_client = None

# Compiled regex pattern for email validation
EMAIL_PATTERN = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')

def load_cdk_outputs():
    """Load CDK outputs and return both outputs dict and stack_id"""
    import os
    cdk_output_path = 'webapp/cdk-outputs.json'
    
    if os.path.exists(cdk_output_path):
        try:
            with open(cdk_output_path, 'r', encoding='utf-8') as f:
                outputs = json.load(f)
            stack_id = list(outputs.keys())[0]
            return outputs[stack_id], stack_id
        except (json.JSONDecodeError, KeyError, IndexError):
            pass
    return None, None

def create_user(user_pool_id, email):
    """Create Cognito user with Cognito-generated temporary password sent via email"""
    # Validate email input from user
    if not validate_email(email):
        raise ValueError("Invalid email format")
    
    try:
        response = cognito_client.admin_create_user(
            UserPoolId=user_pool_id,
            Username=email,
            UserAttributes=[
                {'Name': 'email', 'Value': email},
                {'Name': 'email_verified', 'Value': 'true'}
            ],
            DesiredDeliveryMediums=['EMAIL']
        )
        
        print(f"✅ Cognito user created successfully")
        print(f"📧 Email: {email}")
        print(f"📨 Temporary password sent to user's email")
        print(f"⚠️  User must change password on first login")
        
        return {
            'user': response['User']
        }
        
    except ClientError as e:
        if e.response['Error']['Code'] == 'UsernameExistsException':
            print(f"❌ User {email} already exists")
        else:
            print(f"❌ Error creating user: {e.response['Error']['Code']}")
        raise

def validate_email(email):
    """Validate email format"""
    return EMAIL_PATTERN.match(email) is not None

def main():
    parser = argparse.ArgumentParser(description='Create Cognito user')
    parser.add_argument('email', help='User email address')
    parser.add_argument('--profile', help='AWS profile name', required=True)
    args = parser.parse_args()
    
    email = args.email
    
    if not validate_email(email):
        print("❌ Invalid email format")
        sys.exit(1)
    
    cdk_outputs, stack_id = load_cdk_outputs()
    if not cdk_outputs or not stack_id:
        print("❌ Could not load CDK outputs. Run './setup.sh' first.")
        sys.exit(1)
    
    # Always use region from CDK outputs, never from profile
    region = cdk_outputs.get('Region')
    
    if not region:
        print("❌ Region not found in CDK outputs")
        sys.exit(1)
    
    # Initialize boto3 client with explicit profile and region
    session = boto3.Session(profile_name=args.profile, region_name=region)
    global cognito_client
    cognito_client = session.client('cognito-idp')
    
    user_pool_id = cdk_outputs.get('CognitoUserPoolId')
    cloudfront_url = cdk_outputs.get('CloudFrontURL')
    
    if not user_pool_id:
        print("❌ CognitoUserPoolId not found in CDK outputs")
        sys.exit(1)
    
    if not cloudfront_url:
        print("❌ CloudFrontURL not found in CDK outputs")
        sys.exit(1)
    
    try:
        create_user(user_pool_id, email)
    except (ValueError, ClientError) as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
