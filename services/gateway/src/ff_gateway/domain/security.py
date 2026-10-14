"""Password hashing (bcrypt) and JWT issue/verify."""

import hashlib
import uuid
from datetime import timedelta
from typing import Any

import bcrypt
import jwt

from ff_gateway.domain.clock import Clock
from ff_gateway.domain.errors import InvalidToken, TokenExpired


def hash_password(password: str, rounds: int = 12) -> str:
    return bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt(rounds)).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode()[:72], hashed.encode())
    except ValueError:
        return False


def hash_jti(jti: str) -> str:
    """Only the SHA-256 of a refresh token id is stored server-side."""
    return hashlib.sha256(jti.encode()).hexdigest()


class RefreshClaims:
    __slots__ = ("user_id", "jti", "family", "expires_at")

    def __init__(self, user_id: str, jti: str, family: str, expires_at: int) -> None:
        self.user_id, self.jti, self.family, self.expires_at = user_id, jti, family, expires_at


class TokenService:
    def __init__(
        self, secret: str, clock: Clock, access_ttl: int, refresh_ttl: int, algorithm: str = "HS256"
    ):
        self._secret, self._clock, self._alg = secret, clock, algorithm
        self.access_ttl, self.refresh_ttl = access_ttl, refresh_ttl

    def _encode(self, user_id: str, typ: str, ttl: int) -> str:
        now = self._clock.now()
        claims = {
            "sub": user_id,
            "typ": typ,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=ttl)).timestamp()),
        }
        return jwt.encode(claims, self._secret, algorithm=self._alg)

    def access(self, user_id: str) -> str:
        return self._encode(user_id, "access", self.access_ttl)

    def new_refresh(self, user_id: str, family: str | None = None) -> tuple[str, RefreshClaims]:
        """Mint a refresh token carrying a unique jti and a family id (one family per login)."""
        now = self._clock.now()
        jti, fam = uuid.uuid4().hex, family or uuid.uuid4().hex
        exp = int((now + timedelta(seconds=self.refresh_ttl)).timestamp())
        claims = {
            "sub": user_id,
            "typ": "refresh",
            "iat": int(now.timestamp()),
            "exp": exp,
            "jti": jti,
            "fam": fam,
        }
        return jwt.encode(claims, self._secret, algorithm=self._alg), RefreshClaims(
            user_id, jti, fam, exp
        )

    def decode_refresh(self, token: str, check_exp: bool = True) -> RefreshClaims:
        try:
            c: dict[str, Any] = jwt.decode(
                token, self._secret, algorithms=[self._alg],
                options={"verify_exp": False, "require": ["sub", "exp", "typ", "jti", "fam"]},
            )  # fmt: skip
        except jwt.PyJWTError as e:
            raise InvalidToken() from e
        if c.get("typ") != "refresh":
            raise InvalidToken("Expected a refresh token")
        if check_exp and self._clock.now().timestamp() >= c["exp"]:
            raise TokenExpired()
        return RefreshClaims(str(c["sub"]), str(c["jti"]), str(c["fam"]), int(c["exp"]))

    def decode(self, token: str, expected_type: str) -> str:
        """Return the user id or raise TokenExpired / InvalidToken. Expiry uses our clock."""
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                self._secret,
                algorithms=[self._alg],
                options={"verify_exp": False, "require": ["sub", "exp", "typ"]},
            )
        except jwt.PyJWTError as e:
            raise InvalidToken() from e
        if claims.get("typ") != expected_type:
            raise InvalidToken(f"Expected a {expected_type} token")
        if self._clock.now().timestamp() >= claims["exp"]:
            raise TokenExpired()
        return str(claims["sub"])
