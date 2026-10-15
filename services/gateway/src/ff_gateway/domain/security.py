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


ISSUER = "ff-gateway"
AUDIENCE = "ff-api"


def _check_iss_aud(c: dict[str, Any]) -> None:
    """Tokens minted before iss/aud existed are still accepted (they expire within the refresh TTL); any other value is not."""
    if c.get("iss", ISSUER) != ISSUER:
        raise InvalidToken()
    aud = c.get("aud", AUDIENCE)
    if aud != AUDIENCE and not (isinstance(aud, list) and AUDIENCE in aud):
        raise InvalidToken()


class RefreshClaims:
    __slots__ = ("user_id", "jti", "family", "expires_at")

    def __init__(self, user_id: str, jti: str, family: str, expires_at: int) -> None:
        self.user_id, self.jti, self.family, self.expires_at = user_id, jti, family, expires_at


class TokenService:
    def __init__(
        self, secret: str, clock: Clock, access_ttl: int, refresh_ttl: int, algorithm: str = "HS256",
        previous_secret: str | None = None,
    ):
        if algorithm not in ("HS256", "HS384", "HS512"):
            raise ValueError("unsupported JWT algorithm")
        self._secret, self._clock, self._alg = secret, clock, algorithm
        self._verify_keys = [secret, *([previous_secret] if previous_secret else [])]
        self.access_ttl, self.refresh_ttl = access_ttl, refresh_ttl

    def _encode(self, user_id: str, typ: str, ttl: int, tv: int | None = None) -> str:
        now = self._clock.now()
        claims = {
            "sub": user_id,
            "iss": ISSUER,
            "aud": AUDIENCE,
            "typ": typ,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=ttl)).timestamp()),
        }
        if tv is not None:
            claims["tv"] = tv
        return jwt.encode(claims, self._secret, algorithm=self._alg)

    def access(self, user_id: str, token_version: int = 0) -> str:
        """``tv`` = the user's token_version at issue time; a later bump (password change, logout-all, deactivation) kills the token."""
        return self._encode(user_id, "access", self.access_ttl, token_version)

    def new_refresh(self, user_id: str, family: str | None = None) -> tuple[str, RefreshClaims]:
        """Mint a refresh token carrying a unique jti and a family id (one family per login)."""
        now = self._clock.now()
        jti, fam = uuid.uuid4().hex, family or uuid.uuid4().hex
        exp = int((now + timedelta(seconds=self.refresh_ttl)).timestamp())
        claims = {
            "sub": user_id,
            "iss": ISSUER,
            "aud": AUDIENCE,
            "typ": "refresh",
            "iat": int(now.timestamp()),
            "exp": exp,
            "jti": jti,
            "fam": fam,
        }
        return jwt.encode(claims, self._secret, algorithm=self._alg), RefreshClaims(
            user_id, jti, fam, exp
        )

    def _decode(self, token: str, required: list[str]) -> dict[str, Any]:
        err: Exception | None = None
        for key in self._verify_keys:
            try:
                c: dict[str, Any] = jwt.decode(
                    token, key, algorithms=[self._alg],
                    options={"verify_exp": False, "verify_aud": False, "require": required},
                )
            except jwt.InvalidSignatureError as e:  # maybe signed with the other key
                err = e
                continue
            except jwt.PyJWTError as e:
                raise InvalidToken() from e
            _check_iss_aud(c)
            if isinstance(c["exp"], bool) or not isinstance(c["exp"], int | float) or not isinstance(c["sub"], str):
                raise InvalidToken()  # a malformed (but correctly signed) claim must be a 401, never a 500
            nbf = c.get("nbf")
            if nbf is not None and (not isinstance(nbf, int | float) or self._clock.now().timestamp() < nbf):
                raise InvalidToken()
            return c
        raise InvalidToken() from err

    def decode_refresh(self, token: str, check_exp: bool = True) -> RefreshClaims:
        c = self._decode(token, ["sub", "exp", "typ", "jti", "fam"])
        if c.get("typ") != "refresh":
            raise InvalidToken("Expected a refresh token")
        if check_exp and self._clock.now().timestamp() >= c["exp"]:
            raise TokenExpired()
        return RefreshClaims(str(c["sub"]), str(c["jti"]), str(c["fam"]), int(c["exp"]))

    def decode_with_version(self, token: str, expected_type: str) -> tuple[str, int | None]:
        """(user id, ``tv`` claim or None for tokens minted before it existed). Raises TokenExpired / InvalidToken."""
        claims = self._decode(token, ["sub", "exp", "typ"])
        if claims.get("typ") != expected_type:
            raise InvalidToken(f"Expected a {expected_type} token")
        if self._clock.now().timestamp() >= claims["exp"]:
            raise TokenExpired()
        tv = claims.get("tv")
        if tv is not None and (isinstance(tv, bool) or not isinstance(tv, int)):
            raise InvalidToken()
        return str(claims["sub"]), tv

    def decode(self, token: str, expected_type: str) -> str:
        """Return the user id or raise TokenExpired / InvalidToken. Expiry uses our clock."""
        return self.decode_with_version(token, expected_type)[0]


def token_version_ok(tv: int | None, user_version: int | None) -> bool:
    """A token carrying ``tv`` must match the user's current version; tokens issued before ``tv`` existed (None) are
    accepted only while the user's version is still 0 (i.e. nothing has been revoked since the rollout)."""
    uv = user_version or 0
    return uv == 0 if tv is None else tv == uv
