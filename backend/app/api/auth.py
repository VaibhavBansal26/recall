from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.auth import COOKIE_NAME, AuthService, LoginLimiter, client_key
from app.config import get_settings

router = APIRouter(prefix="/api/auth")


class LoginIn(BaseModel):
    passphrase: str = Field(min_length=1, max_length=512)


class AuthStatus(BaseModel):
    auth_required: bool
    authenticated: bool


@router.get("/me", response_model=AuthStatus)
async def me(request: Request) -> AuthStatus:
    auth: AuthService = request.app.state.auth
    return AuthStatus(
        auth_required=auth.enabled,
        authenticated=auth.verify(request.cookies.get(COOKIE_NAME)),
    )


@router.post("/login", response_model=AuthStatus)
async def login(body: LoginIn, request: Request, response: Response) -> AuthStatus:
    auth: AuthService = request.app.state.auth
    limiter: LoginLimiter = request.app.state.login_limiter
    if not auth.enabled:
        return AuthStatus(auth_required=False, authenticated=True)

    key = client_key(request)
    wait = limiter.retry_after(key)
    if wait:
        raise HTTPException(
            status_code=429,
            detail="Too many attempts. Try again later.",
            headers={"Retry-After": str(wait)},
        )
    if not auth.check_passphrase(body.passphrase):
        limiter.record_failure(key)
        raise HTTPException(status_code=401, detail="Wrong passphrase")

    limiter.reset(key)
    response.set_cookie(
        COOKIE_NAME,
        auth.issue(),
        max_age=auth.max_age,
        httponly=True,
        secure=get_settings().cookie_secure,
        samesite="lax",
        path="/",
    )
    return AuthStatus(auth_required=True, authenticated=True)


@router.post("/logout", response_model=AuthStatus)
async def logout(request: Request, response: Response) -> AuthStatus:
    response.delete_cookie(COOKIE_NAME, path="/")
    return AuthStatus(auth_required=request.app.state.auth.enabled, authenticated=False)
