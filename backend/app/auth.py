"""Single-user passphrase login with a signed, long-lived session cookie."""

import hashlib
import hmac
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request
from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.config import LOCAL_USER_ID, Settings

COOKIE_NAME = "recall_session"


class AuthService:
    def __init__(self, settings: Settings) -> None:
        self.enabled = bool(settings.auth_passphrase)
        self.max_age = settings.session_days * 86400
        self._passphrase_digest = hashlib.sha256(settings.auth_passphrase.encode()).digest()
        self._serializer = URLSafeTimedSerializer(settings.session_secret, salt="recall-session")

    def check_passphrase(self, supplied: str) -> bool:
        # Compare fixed-length digests so neither length nor content leaks through timing.
        digest = hashlib.sha256(supplied.encode()).digest()
        return self.enabled and hmac.compare_digest(digest, self._passphrase_digest)

    def issue(self) -> str:
        return self._serializer.dumps({"u": str(LOCAL_USER_ID)})

    def verify(self, token: str | None) -> bool:
        if not self.enabled:
            return True
        if not token:
            return False
        try:
            data = self._serializer.loads(token, max_age=self.max_age)
        except BadSignature:  # also covers SignatureExpired
            return False
        return isinstance(data, dict) and data.get("u") == str(LOCAL_USER_ID)


class LoginLimiter:
    """Blocks a client after too many wrong passphrases in a time window."""

    def __init__(self, max_failures: int = 5, window_s: int = 600) -> None:
        self.max_failures = max_failures
        self.window_s = window_s
        self._failures: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, key: str, now: float) -> deque[float]:
        q = self._failures[key]
        while q and now - q[0] > self.window_s:
            q.popleft()
        return q

    def retry_after(self, key: str, now: float | None = None) -> int:
        """Seconds until another attempt is allowed; 0 if allowed now."""
        now = time.monotonic() if now is None else now
        q = self._prune(key, now)
        if len(q) < self.max_failures:
            return 0
        return max(1, int(self.window_s - (now - q[0])))

    def record_failure(self, key: str, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        self._prune(key, now).append(now)

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)


def client_key(request: Request) -> str:
    """Caddy sets X-Forwarded-For; fall back to the socket peer when run directly."""
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return forwarded or (request.client.host if request.client else "unknown")


async def require_auth(request: Request) -> None:
    auth: AuthService = request.app.state.auth
    if not auth.verify(request.cookies.get(COOKIE_NAME)):
        raise HTTPException(status_code=401, detail="Not authenticated")


async def require_auth_or_secret(request: Request) -> None:
    """Browser session cookie, or the shared secret n8n sends in `X-Recall-Secret`."""
    auth: AuthService = request.app.state.auth
    supplied = request.headers.get("x-recall-secret")
    expected: str = request.app.state.recall_secret
    if (
        expected
        and supplied
        and hmac.compare_digest(
            hashlib.sha256(supplied.encode()).digest(), hashlib.sha256(expected.encode()).digest()
        )
    ):
        return
    if not auth.verify(request.cookies.get(COOKIE_NAME)):
        raise HTTPException(status_code=401, detail="Not authenticated")
