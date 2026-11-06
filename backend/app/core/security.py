import hmac
import time
from collections import defaultdict, deque
import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from app.core.config import settings
from app.core.errors import AppError

bearer = HTTPBearer(auto_error=False)
failures = defaultdict(deque)
WINDOW_SECONDS = 60
MAX_FAILURES = 5


def configured():
    return bool(settings.admin_password) and len(settings.jwt_secret) >= 16


def login(username, password, ip):
    if not configured():
        raise AppError("Login is not configured: set ADMIN_PASSWORD and a JWT_SECRET of 16+ characters in .env", 503)
    recent = failures[ip]
    cutoff = time.monotonic() - WINDOW_SECONDS
    while recent and recent[0] < cutoff:
        recent.popleft()
    if len(recent) >= MAX_FAILURES:
        raise AppError("Too many failed logins, wait a minute and try again", 429)
    user_ok = hmac.compare_digest(username.encode(), settings.admin_username.encode())
    pass_ok = hmac.compare_digest(password.encode(), settings.admin_password.encode())
    if not (user_ok and pass_ok):
        recent.append(time.monotonic())
        raise AppError("Wrong username or password", 401)
    seconds = settings.jwt_hours * 3600
    token = jwt.encode({"sub": username, "exp": int(time.time()) + seconds}, settings.jwt_secret, algorithm="HS256")
    return {"access_token": token, "token_type": "bearer", "expires_in": seconds}


def require_auth(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if not configured():
        raise AppError("Login is not configured on the server", 503)
    if not credentials:
        raise AppError("Not authenticated", 401)
    try:
        payload = jwt.decode(credentials.credentials, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise AppError("Invalid or expired token", 401) from None
    return payload["sub"]