"""One error format for every failure: {"error": {"code", "message", "request_id"}}.

Codes follow the Security & Observability Architecture catalogue (MM-<AREA>-<NNN>). No stack
traces or internal details reach the client; they go to the log with the request id.
"""

import logging

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.request_context import request_id

log = logging.getLogger("api")

# code: (HTTP status, default message)
CODES = {
    "MM-REQ-001": (422, "The request is not valid."),
    "MM-REQ-002": (413, "The request body is too large."),
    "MM-REQ-003": (404, "Not found."),
    "MM-QUOTA-001": (429, "Daily chat limit reached. Try again tomorrow."),
    "MM-DB-001": (503, "The database is not reachable right now."),
    "MM-DB-002": (504, "The database took too long to answer."),
    "MM-DATA-001": (200, "Serving the last available regime; today's data is not in yet."),
    "MM-LLM-001": (504, "The AI analyst took too long to answer."),
    "MM-LLM-002": (503, "The AI analyst is busy - try again in a minute."),
    "MM-LLM-003": (502, "The AI analyst returned an error."),
    "MM-LLM-004": (200, "The answer was cut short after the maximum number of tool rounds."),
    "MM-LLM-005": (200, "Part of the answer was replaced by a safety check."),
    "MM-TOOL-001": (200, "A data tool failed; the analyst was told the data is unavailable."),
    "MM-CFG-001": (503, "The service is not configured correctly."),
    "MM-INT-001": (500, "Something went wrong on our side."),
}


class ApiError(Exception):
    def __init__(self, code, message=None, status=None, details=None):
        default_status, default_message = CODES.get(code, (500, "Error"))
        super().__init__(message or default_message)
        self.code = code
        self.message = message or default_message
        self.status = status or default_status
        self.details = details


def error_body(code, message, details=None):
    body = {"error": {"code": code, "message": message, "request_id": request_id()}}
    if details:
        body["error"]["details"] = details
    return body


def error_response(code, message=None, status=None, details=None, headers=None):
    err = ApiError(code, message, status, details)
    return JSONResponse(
        error_body(err.code, err.message, err.details), status_code=err.status, headers=headers
    )


async def _api_error(_: Request, exc: ApiError):
    if exc.status >= 500:
        log.warning("%s %s", exc.code, exc.message)
    return JSONResponse(error_body(exc.code, exc.message, exc.details), status_code=exc.status)


async def _validation_error(_: Request, exc: RequestValidationError):
    details = [
        {"field": ".".join(str(p) for p in e.get("loc", ())[1:]), "problem": e.get("msg", "")}
        for e in exc.errors()
    ]
    return JSONResponse(error_body("MM-REQ-001", CODES["MM-REQ-001"][1], details), status_code=422)


async def _http_error(_: Request, exc: StarletteHTTPException):
    code = {404: "MM-REQ-003", 405: "MM-REQ-001", 413: "MM-REQ-002"}.get(exc.status_code, "MM-INT-001")
    message = CODES[code][1] if exc.status_code != 405 else "Method not allowed."
    return JSONResponse(error_body(code, message), status_code=exc.status_code)


async def _unexpected(_: Request, exc: Exception):
    log.exception("Unhandled error (request %s)", request_id())
    return JSONResponse(error_body("MM-INT-001", CODES["MM-INT-001"][1]), status_code=500)


def install(app):
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(Exception, _unexpected)
