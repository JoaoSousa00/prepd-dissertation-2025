import logging
from typing import List, Optional

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import JSONResponse
from src.application.incident_details import IncidentDetailsService
from src.application.incident_fetching import IncidentFetchingService
from src.domain.incident import IncidentSourceUnauthorizedError
from src.infrastructure.itsm_client import ItsmIncidentSourceAdapter
from src.infrastructure.llm_gateway import GaiaLlmGatewayAdapter
from src.shared.http.models import (
    DetailsResponse,
    ErrorResponse,
    IncidentData,
    LlmUsageData,
    ResolutionSuggestion,
)

router = APIRouter(prefix="/incident", tags=["Incidents"])
logger = logging.getLogger(__name__)


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

    incident_details_service = get_incident_details_service(request)
    try:
        incident_details = incident_details_service.fetch_incident_details(incidentIds)
    except IncidentSourceUnauthorizedError as exc:
        return create_unauthorized_response(str(exc))
    return DetailsResponse(
        incidents=[
            IncidentData(
                id=incident.id,
                shortDescription=incident.short_description,
                description=incident.description,
                summary=incident.summary,
                relatedIncidents=incident.related_incidents or None,
                resolutionSuggestions=[
                    ResolutionSuggestion(
                        suggestion=suggestion.suggestion,
                        relatedIncidents=suggestion.related_incidents,
                    )
                    for suggestion in incident.resolution_suggestions
                ]
                or None,
                llmUsage=(
                    LlmUsageData(
                        model=incident.llm_usage.model,
                        tokensIn=incident.llm_usage.tokens_in,
                        tokensOut=incident.llm_usage.tokens_out,
                        tokensTotal=incident.llm_usage.tokens_total,
                        cost_USD=incident.llm_usage.estimated_cost,
                    )
                    if incident.llm_usage is not None
                    else None
                ),
                requestLatencyMs=incident.request_latency_ms,
            )
            for incident in incident_details
        ]
    )


def get_incident_details_service(request: Request) -> IncidentDetailsService:
    service = getattr(request.app.state, "incident_details_service", None)
    if service is None:
        incident_fetching_service = IncidentFetchingService(ItsmIncidentSourceAdapter())
        llm_gateway = _build_llm_gateway()
        service = IncidentDetailsService(
            incident_fetching_service=incident_fetching_service,
            llm_gateway=llm_gateway,
        )
        request.app.state.incident_details_service = service
    return service


def _build_llm_gateway() -> Optional[GaiaLlmGatewayAdapter]:
    try:
        return GaiaLlmGatewayAdapter()
    except ValueError as exc:
        logger.warning("LLM gateway disabled due to configuration error: %s", exc)
        return None
