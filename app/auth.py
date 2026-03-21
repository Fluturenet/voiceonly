# app/auth.py
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import secrets
from app.config import settings

security = HTTPBasic()

def verify_password(credentials: HTTPBasicCredentials = Depends(security)):
    """
    Verify the password against the one stored in password.txt
    Uses constant-time comparison to prevent timing attacks
    """
        
    correct_password = settings.PASSWORD
    
    # Constant time comparison to prevent timing attacks
    is_correct = secrets.compare_digest(
        credentials.password.encode("utf8"),
        correct_password.encode("utf8")
    )
    
    if not is_correct:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect password",
            headers={"WWW-Authenticate": "Basic"},
        )
    
    return True

# Optional: create a dependency for admin routes
def require_auth(auth: bool = Depends(verify_password)):
    """Dependency to protect routes that need authentication"""
    return auth
