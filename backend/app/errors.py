"""A typed error taxonomy, served as RFC 9457 problem details.

V1 through V3 raised ``HTTPException`` with a prose string. That is fine for a
human reading a 409 in a browser and useless for anything else: a client cannot
branch on prose, a log aggregator cannot count it, and the same logical failure
worded two different ways in two routers becomes two different errors.

Every failure this application can produce now has a **stable machine code**
alongside the prose, and the prose is kept - the explanations are the most
useful thing the API returns and several of them took a bug to write. The
response body follows RFC 9457 (``application/problem+json``):

    {
      "type": "https://strategysphere.dev/errors/stage-order",
      "title": "Pipeline stage out of order",
      "status": 409,
      "code": "STAGE_ORDER",
      "detail": "Run the market attractiveness matrix first. ...",
      "instance": "/companies/0c8.../uncertainty",
      "request_id": "01JB2..."
    }

``detail`` is exactly what ``HTTPException(detail=...)`` used to carry, so every
existing client - including this project's own frontend, which reads
``detail`` - keeps working unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

ERROR_BASE_URL = "https://strategysphere.dev/errors"


@dataclass(frozen=True)
class ErrorKind:
    code: str
    status: int
    title: str
    slug: str

    @property
    def type_url(self) -> str:
        return f"{ERROR_BASE_URL}/{self.slug}"


# The closed set. A failure mode that is not in here is a failure mode nobody
# named, which is how "something went wrong" ends up in a payload.
NOT_FOUND = ErrorKind("NOT_FOUND", 404, "Resource not found", "not-found")
STAGE_ORDER = ErrorKind("STAGE_ORDER", 409, "Pipeline stage out of order", "stage-order")
INSUFFICIENT_INPUT = ErrorKind(
    "INSUFFICIENT_INPUT", 409, "Not enough input to compute anything", "insufficient-input"
)
INVALID_INPUT = ErrorKind("INVALID_INPUT", 422, "Input rejected", "invalid-input")
CONFLICT = ErrorKind("CONFLICT", 409, "Conflicting request", "conflict")
BUDGET_INFEASIBLE = ErrorKind(
    "BUDGET_INFEASIBLE", 409, "Portfolio cannot be funded as stated", "budget-infeasible"
)
UPSTREAM_UNAVAILABLE = ErrorKind(
    "UPSTREAM_UNAVAILABLE", 502, "An upstream source could not be reached", "upstream-unavailable"
)
NOT_CONFIGURED = ErrorKind(
    "NOT_CONFIGURED", 503, "The server is missing required configuration", "not-configured"
)
JOB_CONFLICT = ErrorKind("JOB_CONFLICT", 409, "Job is not in a state that allows this", "job-conflict")
RATE_LIMITED = ErrorKind("RATE_LIMITED", 429, "Too many requests", "rate-limited")
INTERNAL = ErrorKind("INTERNAL", 500, "Unhandled server error", "internal")


class AppError(Exception):
    """Every deliberate failure in the application is one of these.

    ``extra`` carries structured context - the shortfall on an infeasible
    budget, the stage that is missing, the unknown input keys - so a client can
    render something useful without parsing the prose.
    """

    def __init__(self, kind: ErrorKind, detail: str, **extra: Any) -> None:
        super().__init__(detail)
        self.kind = kind
        self.detail = detail
        self.extra = extra

    def to_problem(self, instance: str | None = None, request_id: str | None = None) -> dict[str, Any]:
        problem: dict[str, Any] = {
            "type": self.kind.type_url,
            "title": self.kind.title,
            "status": self.kind.status,
            "code": self.kind.code,
            "detail": self.detail,
        }
        if instance:
            problem["instance"] = instance
        if request_id:
            problem["request_id"] = request_id
        problem.update(self.extra)
        return problem


# --- convenience constructors, so call sites stay one line -----------------

def not_found(what: str, identifier: Any) -> AppError:
    return AppError(NOT_FOUND, f"{what} {identifier} not found", resource=what)


def stage_order(detail: str, *, needs: str) -> AppError:
    return AppError(STAGE_ORDER, detail, missing_stage=needs)


def invalid_input(detail: str, **extra: Any) -> AppError:
    return AppError(INVALID_INPUT, detail, **extra)


def install_handlers(app: Any) -> None:
    """Register the handlers that turn errors into problem documents.

    Also wraps FastAPI's own ``HTTPException`` and request-validation failures,
    so the body shape is identical no matter which layer rejected the call. A
    client that special-cases "our errors look like X, FastAPI's look like Y" is
    a client that breaks on the next refactor.
    """
    from fastapi.exceptions import RequestValidationError
    from starlette.exceptions import HTTPException as StarletteHTTPException

    def _request_id(request: Request) -> str | None:
        return getattr(request.state, "request_id", None)

    def _respond(problem: dict[str, Any]) -> JSONResponse:
        return JSONResponse(
            status_code=int(problem["status"]),
            content=problem,
            media_type="application/problem+json",
        )

    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        return _respond(exc.to_problem(str(request.url.path), _request_id(request)))

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        kind = {
            404: NOT_FOUND,
            409: CONFLICT,
            422: INVALID_INPUT,
            429: RATE_LIMITED,
            501: NOT_CONFIGURED,
        }.get(exc.status_code)
        if kind is None:
            kind = ErrorKind(
                code=f"HTTP_{exc.status_code}",
                status=exc.status_code,
                title=str(exc.detail)[:80] if exc.detail else "Request failed",
                slug="http",
            )
        error = AppError(kind, str(exc.detail))
        problem = error.to_problem(str(request.url.path), _request_id(request))
        problem["status"] = exc.status_code
        return _respond(problem)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Keep FastAPI's per-field errors under `errors`, because they are
        # genuinely useful, while `detail` stays a readable sentence.
        fields = [
            {
                "field": ".".join(str(p) for p in err.get("loc", [])[1:]) or "body",
                "message": err.get("msg", ""),
                "type": err.get("type", ""),
            }
            for err in exc.errors()
        ]
        summary = "; ".join(f"{f['field']}: {f['message']}" for f in fields) or "Invalid request"
        error = AppError(INVALID_INPUT, summary, errors=fields)
        return _respond(error.to_problem(str(request.url.path), _request_id(request)))
