"""
Firebase Authentication Middleware and Utilities
"""
from fastapi import HTTPException, Depends, Header
from typing import Optional
import firebase_admin
from firebase_admin import credentials, auth
import os
from dotenv import load_dotenv

# Load .env file - specify the path explicitly
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
print(f"DEBUG: Loading .env from: {env_path}")
print(f"DEBUG: .env file exists: {os.path.exists(env_path)}")

# Try loading with override=True to ensure it loads
result = load_dotenv(dotenv_path=env_path, override=True)
print(f"DEBUG: load_dotenv result: {result}")

# Debug: Print all loaded env vars starting with FIREBASE
import os
for key in os.environ.keys():
    if 'FIREBASE' in key:
        print(f"DEBUG: Found env var {key} = {os.environ[key]}")

# Initialize Firebase Admin SDK
# Option 1: Using service account JSON file (for local development)
# Option 2: Using Application Default Credentials (for GCP deployment)
try:
    if not firebase_admin._apps:
        # Try service account path first (local development)
        service_account_path = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH")
        print(f"DEBUG: FIREBASE_SERVICE_ACCOUNT_PATH from env: {service_account_path}")
        if service_account_path:
            # Convert relative path to absolute path
            if not os.path.isabs(service_account_path):
                # Get directory where auth.py is located
                current_dir = os.path.dirname(os.path.abspath(__file__))
                service_account_path = os.path.join(current_dir, service_account_path)
            
            print(f"DEBUG: Resolved service account path: {service_account_path}")
            print(f"DEBUG: Service account file exists: {os.path.exists(service_account_path)}")
            
            if os.path.exists(service_account_path):
                cred = credentials.Certificate(service_account_path)
                firebase_admin.initialize_app(cred)
                print("Firebase Admin initialized with service account")
            else:
                print(f"Firebase service account file not found: {service_account_path}")
        else:
            # Try Application Default Credentials (for GCP deployment)
            project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
            if project_id:
                firebase_admin.initialize_app()
                print("Firebase Admin initialized with Application Default Credentials")
            else:
                print("Firebase initialization warning: No credentials found")
                print("Set FIREBASE_SERVICE_ACCOUNT_PATH or GOOGLE_CLOUD_PROJECT environment variable")
except Exception as e:
    print(f"Firebase initialization error: {e}")
    print("Firebase Admin will not be initialized - token verification will fail")


async def verify_firebase_token(
    authorization: Optional[str] = Header(None)
) -> dict:
    """
    Verify Firebase ID token from Authorization header.
    Returns the decoded token with user information.
    """
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Authorization header missing"
        )
    
    # Extract token from "Bearer <token>"
    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            raise ValueError("Invalid authorization scheme")
    except ValueError:
        raise HTTPException(
            status_code=401,
            detail="Invalid authorization header format. Expected: Bearer <token>"
        )
    
    try:
        # Verify the token
        decoded_token = auth.verify_id_token(token)
        return decoded_token
    except auth.ExpiredIdTokenError:
        raise HTTPException(
            status_code=401,
            detail="Firebase token expired"
        )
    except auth.InvalidIdTokenError:
        raise HTTPException(
            status_code=401,
            detail="Invalid Firebase token"
        )
    except Exception as e:
        raise HTTPException(
            status_code=401,
            detail=f"Token verification failed: {str(e)}"
        )


def get_firebase_uid(decoded_token: dict = Depends(verify_firebase_token)) -> str:
    """
    Extract Firebase UID from decoded token.
    Use this as a dependency in your routes.
    """
    uid = decoded_token.get("uid")
    if not uid:
        raise HTTPException(status_code=401, detail="Firebase token missing UID")
    return uid

