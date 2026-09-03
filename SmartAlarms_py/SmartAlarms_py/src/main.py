import logging
import os
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from starlette.status import HTTP_400_BAD_REQUEST

from src.presentation.api.incidents import router as incidents_router
from src.shared.http.models import ErrorResponse
from src.shared.observability import RequestLogContext, bind_request_context, log_request_summary
load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(levelname)s %(name)s: %(message)s",
)

# Suppress noisy HTTP library debug logs even when application DEBUG logging is enabled.
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)


app = FastAPI(
    title="SmartAlarms API",
    version="v1",
    description="API contract for incident analysis and incident detail enrichment.",
    docs_url="/docs",
    openapi_url="/openapi.json",
)


@app.middleware("http")
async def request_observability_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    request.state.request_id = request_id
    context = RequestLogContext(request_id=request_id)
    started_at = time.perf_counter()
    with bind_request_context(context):
        try:
            response = await call_next(request)
            return response
        finally:
            context.latency_ms = (time.perf_counter() - started_at) * 1000
            if request.url.path.startswith("/incident"):
                log_request_summary()


app.include_router(incidents_router)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc: RequestValidationError):
    """Handle Pydantic validation errors"""
    details = []
    for error in exc.errors():
        if error["type"] == "missing":
            details.append(f"{error['loc'][1]} is required")
        elif error["type"] == "value_error":
            details.append(f"{error['loc'][1]}: {error['msg']}")
        else:
            details.append(str(error["msg"]))

    error_response = {
        "message": "Invalid request payload",
        "code": "BAD_REQUEST",
        "details": details,
    }
    return JSONResponse(
        status_code=HTTP_400_BAD_REQUEST,
        content=error_response,
    )


@app.get("/health", tags=["Health"])
async def health_check():
    """Health check endpoint"""
    return {"status": "ok"}
