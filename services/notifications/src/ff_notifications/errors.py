class ApiError(Exception):
    status = 400
    code = "bad_request"

    def __init__(self, message: str, *, code: str | None = None, details: dict | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        self.details = details or {}


class NotFound(ApiError):
    status, code = 404, "not_found"


class Forbidden(ApiError):
    status, code = 403, "forbidden"


class Unauthenticated(ApiError):
    status, code = 401, "unauthenticated"


class Invalid(ApiError):
    status, code = 422, "validation_error"


class TooManyRequests(ApiError):
    status, code = 429, "too_many_requests"


class Conflict(ApiError):
    status, code = 409, "conflict"
