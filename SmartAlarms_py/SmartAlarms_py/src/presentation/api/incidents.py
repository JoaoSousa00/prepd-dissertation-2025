from typing import List, Optional
from fastapi import APIRouter, Query, HTTPException, status
from fastapi.responses import JSONResponse
from src.shared.http.models import DetailsResponse, ErrorResponse

router = APIRouter(prefix="/incident", tags=["Incidents"])


def create_error_response(message: str, code: str, details: List[str] = None):
    """Helper to create error response"""
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "message": message,
            "code": code,
            "details": details or [],
        },
    )


@router.get(
    "/details",
    response_model=DetailsResponse,
    responses={
        200: {"model": DetailsResponse, "description": "Successful retrieval and analysis"},
        204: {"description": "The requested incidents were not found"},
        400: {"model": ErrorResponse, "description": "Invalid request validation"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def get_incident_details(
    incidentIds: List[str] = Query(
        ...,
        description="List of incident identifiers",
    ),
):
    """
    Fetches and analyzes specified incidents.
    
    Returns incident details and analysis-relevant enrichment from related incidents
    and log events for a list of incident identifiers.
    
    - **incidentIds**: List of incident identifiers (required, at least 1)
    """
    # Validate that incidentIds is not empty
    if not incidentIds:
        return create_error_response(
            "Invalid request payload",
            "BAD_REQUEST",
            ["incidentIds is required"],
        )
    
    # Validate that all incident IDs are non-empty strings
    invalid_ids = [id_val for id_val in incidentIds if not id_val or not id_val.strip()]
    if invalid_ids:
        return create_error_response(
            "Invalid request payload",
            "BAD_REQUEST",
            ["incidentIds must be non-empty strings"],
        )

    # For now, return empty response (Phase 1 - no external dependencies)
    return DetailsResponse(incidents=[])
