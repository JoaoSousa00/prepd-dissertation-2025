from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.status import HTTP_422_UNPROCESSABLE_ENTITY
from src.presentation.api.incidents import router as incidents_router
from src.shared.http.models import ErrorResponse


app = FastAPI(
    title="SmartAlarms API",
    version="v1",
    description="API contract for incident analysis and incident detail enrichment.",
    docs_url="/docs",
    openapi_url="/openapi.json",
)

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
        status_code=HTTP_422_UNPROCESSABLE_ENTITY,
        content=error_response,
    )


@app.get("/health", tags=["Health"])
async def health_check():
    """Health check endpoint"""
    return {"status": "ok"}
