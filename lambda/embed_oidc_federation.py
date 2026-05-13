"""ClearOne Advantage - Quick Suite embedding Lambda.

Supports two embedding modes for a single authenticated user (Cognito OIDC federation):
  - getDashboardUrl: returns a Dashboard embed URL (operational reporting)
  - getChatUrl: returns a Quick Suite Chat (QuickChat) embed URL
"""
import json
import os
import logging
import re
import threading
import time
from urllib.parse import urlparse

import boto3
import jwt
import requests
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Thread-safe JWKS cache
_jwks_cache = {"keys": None, "timestamp": 0}
_jwks_cache_lock = threading.Lock()
JWKS_CACHE_TTL = 3600

_sts_client = None
_http_session = None

ARN_PATTERN = re.compile(r"^arn:aws:iam::\d{12}:role/.+$")
COGNITO_DOMAIN_PATTERN = re.compile(r"^https://[a-z0-9-]+\.auth\.[a-z0-9-]+\.amazoncognito\.com$")
COGNITO_JWKS_PATTERN = re.compile(
    r"^https://cognito-idp\.[a-z0-9-]+\.amazonaws\.com/[a-z0-9-]+_[A-Za-z0-9]+/\.well-known/jwks\.json$"
)

REQUIRED_ENV_VARS = [
    "COGNITO_DOMAIN_URL",
    "COGNITO_CLIENT_ID",
    "WEB_IDENTITY_ROLE_ARN",
    "ALLOWED_ORIGIN",
    "COGNITO_USER_POOL_ID",
    "REDIRECT_URI",
    "CLOUDFRONT_DOMAIN",
    "QUICKSIGHT_IDENTITY_REGION",
]


def get_aws_region() -> str:
    if "AWS_REGION" not in os.environ:
        raise ValueError("AWS_REGION environment variable missing")
    return os.environ["AWS_REGION"]


def lambda_handler(event, context):
    for var in REQUIRED_ENV_VARS:
        if var not in os.environ or not os.environ[var]:
            logger.error("Missing required environment variable: %s", var)
            return error_response(500, "Service configuration missing")

    try:
        if event.get("httpMethod") == "OPTIONS":
            return {"statusCode": 200, "headers": cors_headers(), "body": ""}

        query_params = event.get("queryStringParameters") or {}

        if "code" in query_params:
            return handle_auth_code_callback(event, context)

        mode = query_params.get("mode")
        if mode == "getDashboardUrl":
            return handle_embed_request(event, experience="dashboard")
        if mode == "getChatUrl":
            return handle_embed_request(event, experience="chat")
        return error_response(400, "Invalid request. Use CloudFront URL to access the portal.")
    except Exception as e:
        logger.error("Handler error: %s: %s", type(e).__name__, e)
        return error_response(500, "Request processing failed")


def cors_headers() -> dict:
    return {
        "Access-Control-Allow-Origin": os.environ["ALLOWED_ORIGIN"],
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization",
        "Access-Control-Max-Age": "3600",
    }


def handle_auth_code_callback(event, context):
    try:
        query_params = event.get("queryStringParameters") or {}
        auth_code = query_params.get("code")
        if not auth_code:
            return error_response(400, "Authorization code missing")
        tokens = exchange_code_for_tokens(auth_code)
        id_token = tokens.get("id_token")
        if not id_token:
            return error_response(400, "Token missing from response")
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": os.environ["ALLOWED_ORIGIN"],
                "Cache-Control": "no-cache, no-store, must-revalidate",
            },
            "body": json.dumps({"id_token": id_token}),
        }
    except Exception as e:
        logger.error("Auth code exchange failed: %s: %s", type(e).__name__, e)
        return error_response(400, "Token exchange failed")


def validate_url_against_ssrf(url: str, allowed_pattern: re.Pattern, url_type: str) -> bool:
    import ipaddress

    try:
        parsed = urlparse(url)
        if parsed.hostname:
            hostname = parsed.hostname.lower()
            if hostname in ("localhost", "0.0.0.0"):  # nosec B104
                raise ValueError(f"Blocked hostname in {url_type} URL")
            try:
                ip = ipaddress.ip_address(hostname)
                if ip.is_private or ip.is_loopback or ip.is_link_local:
                    raise ValueError(f"Private/loopback/link-local IP in {url_type} URL")
                if str(ip) == "169.254.169.254":
                    raise ValueError(f"AWS metadata service blocked in {url_type} URL")
            except ValueError as e:
                msg = str(e)
                if any(k in msg for k in ("Private", "loopback", "link-local", "metadata")):
                    raise
        if parsed.scheme != "https":
            raise ValueError(f"Non-HTTPS scheme in {url_type} URL")
        if not allowed_pattern.match(url):
            raise ValueError(f"Invalid {url_type} URL format")
        return True
    except Exception as e:
        logger.warning("URL validation failed for %s: %s", url_type, e)
        raise ValueError(f"Invalid {url_type} URL")


def exchange_code_for_tokens(auth_code: str) -> dict:
    global _http_session
    if _http_session is None:
        _http_session = requests.Session()
    cognito_domain = os.environ["COGNITO_DOMAIN_URL"]
    validate_url_against_ssrf(cognito_domain, COGNITO_DOMAIN_PATTERN, "Cognito domain")
    try:
        response = _http_session.post(
            f"{cognito_domain}/oauth2/token",
            data={
                "grant_type": "authorization_code",
                "client_id": os.environ["COGNITO_CLIENT_ID"],
                "code": auth_code,
                "redirect_uri": os.environ["REDIRECT_URI"],
            },
            timeout=10,
            verify=True,
        )
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, json.JSONDecodeError) as e:
        logger.warning("Token exchange error: %s: %s", type(e).__name__, e)
        raise ValueError("Token exchange failed") from e


def handle_embed_request(event, experience: str):
    """Generate embed URL for dashboard or chat experience, same auth flow for both."""
    try:
        headers = event.get("headers") or {}
        auth_header = headers.get("Authorization") or headers.get("authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return error_response(401, "Authorization header missing or invalid")
        id_token = auth_header[7:]
        if not id_token:
            return error_response(401, "Authentication token missing")

        user_info = verify_and_decode_jwt(id_token)
        user_email = user_info.get("email")
        if not user_email or user_email.count("@") != 1:
            return error_response(400, "User email missing or invalid in token")

        query_params = event.get("queryStringParameters") or {}
        qs_identity_region = os.environ["QUICKSIGHT_IDENTITY_REGION"]
        # For dashboards, default to identity region; Chat has its own supported regions
        if experience == "chat":
            qs_embed_region = query_params.get("region") or qs_identity_region
        else:
            qs_embed_region = qs_identity_region

        credentials = assume_role_with_web_identity(id_token)
        aws_region = get_aws_region()

        account_id = boto3.Session(
            aws_access_key_id=credentials["AccessKeyId"],
            aws_secret_access_key=credentials["SecretAccessKey"],
            aws_session_token=credentials["SessionToken"],
            region_name=aws_region,
        ).client("sts").get_caller_identity()["Account"]

        qs_identity = _qs_client(credentials, qs_identity_region)
        qs_embed = _qs_client(credentials, qs_embed_region)

        user_arn = _lookup_federated_user(qs_identity, account_id, user_email)
        if not user_arn:
            return _access_denied_response(user_email, experience)

        cloudfront_domain = os.environ["CLOUDFRONT_DOMAIN"]
        allowed_domain = f"https://{cloudfront_domain}"

        if experience == "dashboard":
            dashboard_id = query_params.get("dashboardId") or os.environ.get("DASHBOARD_ID", "")
            if not dashboard_id:
                return error_response(500, "DASHBOARD_ID not configured")
            response = qs_embed.generate_embed_url_for_registered_user(
                AwsAccountId=account_id,
                UserArn=user_arn,
                ExperienceConfiguration={
                    "Dashboard": {
                        "InitialDashboardId": dashboard_id,
                        "FeatureConfigurations": {
                            "StatePersistence": {"Enabled": True},
                            "SharedView": {"Enabled": True},
                        },
                    }
                },
                AllowedDomains=[allowed_domain],
                SessionLifetimeInMinutes=600,
            )
            body = {
                "DashboardEmbedUrl": response["EmbedUrl"],
                "DashboardId": dashboard_id,
                "user": user_email,
            }
        else:  # chat
            response = qs_embed.generate_embed_url_for_registered_user(
                AwsAccountId=account_id,
                UserArn=user_arn,
                ExperienceConfiguration={"QuickChat": {}},
                AllowedDomains=[allowed_domain],
                SessionLifetimeInMinutes=600,
            )
            embed_url = response["EmbedUrl"]
            # Append agentId from env or query so the embedded chat opens with
            # the AnyCompany agent selected by default (rather than 'Unknown').
            agent_id = query_params.get("agentId") or os.environ.get("CHAT_AGENT_ID", "")
            if agent_id:
                sep = "&" if "?" in embed_url else "?"
                embed_url = f"{embed_url}{sep}agentId={agent_id}"
            try:
                parsed = urlparse(embed_url)
                logger.info(
                    "QuickChat embed URL generated host=%s path=%s status=%s region=%s agent=%s",
                    parsed.hostname,
                    parsed.path,
                    response.get("Status"),
                    qs_embed_region,
                    agent_id or "(none)",
                )
            except Exception:
                pass
            body = {"ChatEmbedUrl": embed_url, "user": user_email}

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": os.environ["ALLOWED_ORIGIN"],
            },
            "body": json.dumps(body),
        }
    except ValueError as e:
        logger.error("Validation error: %s", e)
        return error_response(400, str(e))
    except ClientError as e:
        err = e.response["Error"]
        logger.error("AWS service error: %s: %s", err["Code"], err["Message"])
        return error_response(500, f"AWS service error: {err['Code']}")
    except Exception as e:
        logger.error("Embed request failed: %s: %s", type(e).__name__, e)
        return error_response(500, "Embed URL request failed")


def _qs_client(credentials: dict, region: str):
    return boto3.Session(
        aws_access_key_id=credentials["AccessKeyId"],
        aws_secret_access_key=credentials["SecretAccessKey"],
        aws_session_token=credentials["SessionToken"],
        region_name=region,
    ).client("quicksight")


def _lookup_federated_user(qs_identity, account_id: str, user_email: str):
    """Find the federated Quick Suite user whose email matches and UserName is
    <role-name>/<local-part-of-email>. Paginates if needed.
    """
    web_identity_role_arn = os.environ["WEB_IDENTITY_ROLE_ARN"]
    if not ARN_PATTERN.match(web_identity_role_arn):
        logger.error("Invalid WEB_IDENTITY_ROLE_ARN format")
        raise ValueError("Service configuration error")
    web_identity_role_name = web_identity_role_arn.split("/")[-1]
    user_part = user_email.split("@")[0]
    expected_quicksight_username = f"{web_identity_role_name}/{user_part}"

    next_token = None
    while True:
        params = {"AwsAccountId": account_id, "Namespace": "default"}
        if next_token:
            params["NextToken"] = next_token
        response = qs_identity.list_users(**params)
        for user in response.get("UserList", []):
            if user.get("Email") == user_email and user.get("UserName") == expected_quicksight_username:
                return user.get("Arn")
        next_token = response.get("NextToken")
        if not next_token:
            return None


def _access_denied_response(user_email: str, experience: str):
    what = "AnyCompany operations dashboard" if experience == "dashboard" else "AWS Quick Suite chat agent"
    return {
        "statusCode": 403,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": os.environ["ALLOWED_ORIGIN"],
        },
        "body": json.dumps(
            {
                "error": "Access Denied",
                "message": (
                    f"User {user_email} is not registered as a federated user in Amazon Quick Suite. "
                    f"Please ask your administrator to register this user and share the {what}."
                ),
                "user": user_email,
                "access_required": True,
            }
        ),
    }


def verify_and_decode_jwt(token: str) -> dict:
    try:
        cognito_region = get_aws_region()
        user_pool_id = os.environ["COGNITO_USER_POOL_ID"]
        jwks_url = f"https://cognito-idp.{cognito_region}.amazonaws.com/{user_pool_id}/.well-known/jwks.json"
        validate_url_against_ssrf(jwks_url, COGNITO_JWKS_PATTERN, "JWKS")

        global _jwks_cache, _http_session
        current_time = time.time()
        if _jwks_cache["keys"] and (current_time - _jwks_cache["timestamp"]) < JWKS_CACHE_TTL:
            jwks = _jwks_cache["keys"]
        else:
            with _jwks_cache_lock:
                if _jwks_cache["keys"] and (current_time - _jwks_cache["timestamp"]) < JWKS_CACHE_TTL:
                    jwks = _jwks_cache["keys"]
                else:
                    if _http_session is None:
                        _http_session = requests.Session()
                    r = _http_session.get(jwks_url, timeout=10, verify=True)
                    r.raise_for_status()
                    jwks = r.json()
                    if not jwks.get("keys") or not isinstance(jwks["keys"], list):
                        raise ValueError("Invalid JWKS response structure")
                    _jwks_cache["keys"] = jwks
                    _jwks_cache["timestamp"] = current_time

        client_id = os.environ["COGNITO_CLIENT_ID"]
        issuer = f"https://cognito-idp.{cognito_region}.amazonaws.com/{user_pool_id}"
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")
        if not kid:
            raise ValueError("Missing kid in JWT header")
        key = None
        for jwk in jwks["keys"]:
            if jwk.get("kid") == kid:
                key = jwt.algorithms.RSAAlgorithm.from_jwk(jwk)
                break
        if not key:
            raise ValueError("Unable to find signing key")
        return jwt.decode(token, key, algorithms=["RS256"], audience=client_id, issuer=issuer)
    except jwt.InvalidTokenError as e:
        logger.warning("JWT validation failed: %s", e)
        raise ValueError("Token validation failed") from e
    except Exception as e:
        logger.warning("Token verification failed: %s: %s", type(e).__name__, e)
        raise ValueError("Token verification failed") from e


def assume_role_with_web_identity(id_token: str) -> dict:
    global _sts_client
    if _sts_client is None:
        _sts_client = boto3.client("sts", region_name=get_aws_region())
    try:
        response = _sts_client.assume_role_with_web_identity(
            RoleArn=os.environ["WEB_IDENTITY_ROLE_ARN"],
            RoleSessionName=f"AnyCompanyEmbedSession-{int(time.time())}",
            WebIdentityToken=id_token,
            DurationSeconds=3600,
        )
        return response["Credentials"]
    except ClientError as e:
        err = e.response["Error"]
        logger.warning("Role assumption failed: %s: %s", err["Code"], err["Message"])
        raise ValueError("Role assumption failed") from e
    except Exception as e:
        logger.warning("Role assumption failed: %s: %s", type(e).__name__, e)
        raise ValueError("Role assumption failed") from e


def error_response(status_code: int, message: str) -> dict:
    if not message:
        message = "An error occurred"
    if "ALLOWED_ORIGIN" not in os.environ:
        logger.critical("ALLOWED_ORIGIN not configured")
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "Service configuration error"}),
        }
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": os.environ["ALLOWED_ORIGIN"],
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        },
        "body": json.dumps({"error": str(message)}),
    }
