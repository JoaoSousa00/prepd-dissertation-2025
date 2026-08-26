from typing import List, Optional

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import JSONResponse
from src.application.incident_fetching import IncidentFetchingService
from src.domain.incident import IncidentSourceUnauthorizedError
from src.infrastructure.itsm_client import ItsmIncidentSourceAdapter
from src.shared.http.models import DetailsResponse, ErrorResponse, IncidentData

router = APIRouter(prefix="/incident", tags=["Incidents"])


def create_error_response(message: str, code: str, details: Optional[List[str]] = None):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "message": message,
            "code": code,
            "details": details or [],
        },
    )


def create_unauthorized_response(
    message: str,
    code: str = "UNAUTHORIZED",
    details: Optional[List[str]] = None,
):
    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={
            "message": message,
            "code": code,
            "details": details or [],
        },
    )


@router.get(
    "/details",
    response_model=DetailsResponse,
    response_model_exclude_none=True,
    responses={
        200: {"model": DetailsResponse, "description": "Successful retrieval and analysis"},
        204: {"description": "The requested incidents were not found"},
        400: {"model": ErrorResponse, "description": "Invalid request validation"},
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def get_incident_details(
    request: Request,
    incidentIds: List[str] = Query(
        ...,
        description="List of incident identifiers",
    ),
):
    if not incidentIds:
        return create_error_response(
            "Invalid request payload",
            "BAD_REQUEST",
            ["incidentIds is required"],
        )

    invalid_ids = [id_val for id_val in incidentIds if not id_val or not id_val.strip()]
    if invalid_ids:
        return create_error_response(
            "Invalid request payload",
            "BAD_REQUEST",
            ["incidentIds must be non-empty strings"],
        )

    incident_fetching_service = get_incident_fetching_service(request)
    try:
        base_incidents = incident_fetching_service.fetch_base_incidents(incidentIds)
    except IncidentSourceUnauthorizedError as exc:
        return create_unauthorized_response(str(exc))
    return DetailsResponse(
        incidents=[
            IncidentData(
                id=incident.id,
                shortDescription=incident.short_description,
                description=incident.description,
            )
            for incident in base_incidents
        ]
    )


def get_incident_fetching_service(request: Request) -> IncidentFetchingService:
    service = getattr(request.app.state, "incident_fetching_service", None)
    if service is None:
        service = IncidentFetchingService(ItsmIncidentSourceAdapter())
        request.app.state.incident_fetching_service = service
    return service
