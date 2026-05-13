#!/usr/bin/env python3
"""
Delete Cognito user and associated Secrets Manager secret.
Usage: python delete_cognito_user.py <email> [--profile PROFILE]
"""

import sys
import json
import re
import boto3
import argparse
from botocore.exceptions import ClientError

def load_cdk_outputs():
    """Load CDK outputs and return both outputs dict and stack_id"""
    import os
    possible_paths = ['cdk-outputs.json', 'webapp/cdk-outputs.json', '../webapp/cdk-outputs.json']
    
    for path in possible_paths:
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    outputs = json.load(f)
                stack_id = list(outputs.keys())[0]
                return outputs[stack_id], stack_id
            except (json.JSONDecodeError, KeyError, IndexError):
                continue
    return None, None

def delete_user(user_pool_id, email, stack_id, profile=None):
    """Delete Cognito user with validated inputs"""
    # Validate all inputs
    if not user_pool_id or not isinstance(user_pool_id, str):
        raise ValueError("Invalid user_pool_id")
    if not email or not isinstance(email, str):
        raise ValueError("Invalid email")
    if not stack_id or not isinstance(stack_id, str):
        raise ValueError("Invalid stack_id")
    if len(stack_id) > 128:
        raise ValueError("stack_id too long")
    if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9-]*[a-zA-Z0-9]$', stack_id):
        raise ValueError("Invalid stack_id format")
    
    session = boto3.Session(profile_name=profile) if profile else boto3.Session()
    cognito = session.client('cognito-idp')
    secrets_manager = session.client('secretsmanager')
    
    try:
        cognito.admin_delete_user(
            UserPoolId=user_pool_id,
            Username=email
        )
        print(f"✅ Cognito user deleted successfully")
        
    except ClientError as e:
        if e.response['Error']['Code'] == 'UserNotFoundException':
            print(f"⚠️  User not found in pool")
        else:
            print(f"❌ Error deleting user: {str(e)}")
    
    import hashlib
    email_hash = hashlib.sha256(email.encode()).hexdigest()[:8]
    secret_name = f"{stack_id}-cognito-user-{email.replace('@', '-at-').replace('.', '-')}-{email_hash}"
    try:
        secrets_manager.delete_secret(
            SecretId=secret_name,
            ForceDeleteWithoutRecovery=True
        )
        print(f"✅ Secret deleted successfully")
        
    except ClientError as e:
        if e.response['Error']['Code'] == 'ResourceNotFoundException':
            print(f"⚠️  Secret not found")
        else:
            print(f"❌ Error deleting secret: {str(e)}")

def main():
    parser = argparse.ArgumentParser(description='Delete Cognito user')
    parser.add_argument('email', help='User email address')
    parser.add_argument('--profile', help='AWS profile name', required=True)
    args = parser.parse_args()
    
    email = args.email
    
    import re
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(email_pattern, email):
        print("❌ Invalid email format")
        sys.exit(1)
    
    cdk_outputs, stack_id = load_cdk_outputs()
    if not cdk_outputs or not stack_id:
        print("❌ Could not load CDK outputs. Run './setup.sh' first.")
        sys.exit(1)
    
    # Use profile from CDK outputs if not provided
    profile = args.profile or cdk_outputs.get('AWSProfile', 'default')
    
    user_pool_id = cdk_outputs.get('CognitoUserPoolId')
    if not user_pool_id:
        print("❌ CognitoUserPoolId not found in CDK outputs")
        sys.exit(1)
    
    delete_user(user_pool_id, email, stack_id, profile)

if __name__ == "__main__":
    main()
