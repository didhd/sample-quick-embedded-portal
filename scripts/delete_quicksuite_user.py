#!/usr/bin/env python3
"""
Delete QuickSight user that was created with OIDC federation.
Usage: python delete_quicksuite_user.py <email> [--profile PROFILE]
"""

import sys
import json
import boto3
import os
import re
import logging
import argparse
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Suppress boto3/botocore logging
logging.getLogger('boto3').setLevel(logging.CRITICAL)
logging.getLogger('botocore').setLevel(logging.CRITICAL)
logging.getLogger('urllib3').setLevel(logging.CRITICAL)

# Module-level clients for reuse
quicksight_client = None
sts_client = None

# Email validation pattern
EMAIL_PATTERN = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?)*\.[a-zA-Z]{2,}$')


def validate_email(email):
    """Validate email format"""
    if not EMAIL_PATTERN.match(email):
        raise ValueError("Invalid email format")

def load_cdk_outputs():
    """Load CDK outputs from cdk-outputs.json"""
    possible_paths = ['cdk-outputs.json', 'webapp/cdk-outputs.json', '../webapp/cdk-outputs.json']
    
    for path in possible_paths:
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    outputs = json.load(f)
                stack_name = list(outputs.keys())[0]
                return outputs[stack_name]
            except (json.JSONDecodeError, KeyError, IndexError) as e:
                logger.error(f"Error reading {path}: {e}")
                continue
    
    logger.error("cdk-outputs.json not found")
    return None

def find_quicksight_user_by_federated_pattern(email, role_name, account_id, profile, region):
    """Find QuickSight user by email and federated username pattern"""
    validate_email(email)
    
    session = boto3.Session(profile_name=profile, region_name=region)
    global quicksight_client
    quicksight_client = session.client('quicksight')
    
    user_part = email.split('@')[0]
    expected_username = f"{role_name}/{user_part}"
    
    try:
        # Use direct describe_user call instead of pagination for better performance
        response = quicksight_client.describe_user(
            AwsAccountId=account_id,
            Namespace='default',
            UserName=expected_username
        )
        
        user = response.get('User', {})
        if user.get('Email') == email and user.get('UserName') == expected_username:
            return user['UserName']
        
        logger.info(f"QuickSight user {expected_username} found but email mismatch")
        return None
        
    except ClientError as e:
        if e.response['Error']['Code'] == 'ResourceNotFoundException':
            logger.info(f"QuickSight user {expected_username} not found in system")
            return None
        logger.warning(f"Error looking up QuickSight user: {e}")
        raise

def delete_quicksight_user(email, role_name, account_id, profile, region):
    """Delete QuickSight user using federated pattern (idempotent)"""
    session = boto3.Session(profile_name=profile, region_name=region)
    global quicksight_client
    quicksight_client = session.client('quicksight')
    
    # Find the actual username by email and federated pattern
    username = find_quicksight_user_by_federated_pattern(email, role_name, account_id, profile, region)
    if not username:
        logger.info(f"✅ User {email} already deleted or never existed")
        return {'Status': 'AlreadyDeleted'}
    
    try:
        response = quicksight_client.delete_user(
            AwsAccountId=account_id,
            Namespace='default',
            UserName=username
        )
        
        logger.info(f"✅ SUCCESS: QuickSight user deleted!")
        logger.info(f"📧 Email: {email}")
        logger.info(f"👤 Username: {username}")
        
        return response
        
    except ClientError as e:
        if e.response['Error']['Code'] == 'ResourceNotFoundException':
            logger.info(f"✅ User {email} already deleted")
            return {'Status': 'AlreadyDeleted'}
        else:
            logger.warning(f"❌ Failed to delete QuickSight user: {e}")
            raise

def main():
    parser = argparse.ArgumentParser(description='Delete QuickSuite user with OIDC federation')
    parser.add_argument('email', help='User email address')
    parser.add_argument('--profile', help='AWS profile name', required=True)
    args = parser.parse_args()
    
    email = args.email
    
    # Validate email format
    try:
        validate_email(email)
    except ValueError as e:
        print(f"❌ {e}")
        sys.exit(1)
    
    # Load CDK outputs to get role name and region
    cdk_outputs = load_cdk_outputs()
    if not cdk_outputs or 'WebIdentityRoleArn' not in cdk_outputs:
        print("❌ Could not load CDK outputs or WebIdentityRoleArn not found")
        sys.exit(1)
    
    # Get region from CDK outputs
    region = cdk_outputs.get('Region')
    if not region:
        print("❌ Region not found in CDK outputs")
        sys.exit(1)
    
    # Get QuickSight identity region from CDK outputs
    qs_region = cdk_outputs.get('QuickSightIdentityRegion')
    if not qs_region:
        print("❌ QuickSightIdentityRegion not found in CDK outputs")
        sys.exit(1)
    
    # Extract role name from ARN with validation
    role_arn = cdk_outputs['WebIdentityRoleArn']
    if not role_arn or not role_arn.startswith('arn:aws:iam:'):
        print("❌ Invalid WebIdentityRoleArn format")
        sys.exit(1)
    role_name = role_arn.split('/')[-1]
    
    # Get AWS account ID
    session = boto3.Session(profile_name=args.profile, region_name=region)
    global sts_client
    sts_client = session.client('sts')
    
    try:
        account_id = sts_client.get_caller_identity()['Account']
    except ClientError as e:
        print(f"❌ Error getting AWS account ID: {e}")
        sys.exit(1)
    
    print(f"🗑️  Deleting QuickSight user: {email}")
    print(f"🏢 Account ID: {account_id}")
    print(f"📋 QuickSight Identity Region: {qs_region}")
    
    # Delete QuickSight user (idempotent operation)
    try:
        result = delete_quicksight_user(email, role_name, account_id, args.profile, qs_region)
        if result.get('Status') == 'AlreadyDeleted':
            print(f"ℹ️  User was already deleted or never existed")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()