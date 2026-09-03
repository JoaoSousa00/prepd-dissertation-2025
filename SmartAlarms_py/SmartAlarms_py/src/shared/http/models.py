from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict


class LlmUsageData(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "model": "openai/gpt-5",
                "tokensIn": 120,
                "tokensOut": 80,
                "tokensTotal": 200,
                "cost_USD": 0.0123,
            }
        }
    )

    model: Optional[str] = Field(None, description="Model name used for the LLM request")
    tokensIn: Optional[int] = Field(None, description="Prompt token count")
    tokensOut: Optional[int] = Field(None, description="Completion token count")
    tokensTotal: Optional[int] = Field(None, description="Total token count")
    cost_USD: Optional[float] = Field(None, description="Monetary cost in USD")


class ResolutionSuggestion(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "suggestion": "Restart the ECS tasks for the affected service",
                "relatedIncidents": ["INC000000000001", "INC000000000002"],
                "relatedLogIds": ["transactionId1", "transactionId2"],
            }
        }
    )
    
    suggestion: str = Field(..., description="The action that is suggested")
    relatedIncidents: List[str] = Field(
        default_factory=list, description="The list of incidents that led to this suggestion"
    )
    relatedLogIds: Optional[List[str]] = Field(
        None, description="The list of log events that led to this suggestion"
    )


class IncidentData(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "INC000000000000",
                "shortDescription": "An increase of cpu was observed due to a high number of requests to the path /endpoint",
                "description": "The tasks from ECS of the service billing-api were increasing CPU usage due to high requests.",
                "summary": "The billing API is experiencing elevated CPU due to request spikes on /endpoint.",
                "relatedIncidents": ["INC000000000001", "INC000000000002"],
                "resolutionSuggestions": [],
                "relatedLogIds": ["transactionId1", "transactionId2"],
            }
        }
    )
    
    id: str = Field(..., description="The unique incident identifier")
    shortDescription: Optional[str] = Field(
        None, description="A small description of what the incident is about"
    )
    description: Optional[str] = Field(
        None, description="A broader description with incident context"
    )
    summary: Optional[str] = Field(
        None, description="Natural-language summary generated for the incident"
    )
    relatedIncidents: Optional[List[str]] = Field(
        None, description="Related incident references when available"
    )
    resolutionSuggestions: Optional[List[ResolutionSuggestion]] = Field(
        None, description="The list of ordered suggestions to mitigate the incident"
    )
    relatedLogIds: Optional[List[str]] = Field(
        None, description="The list of log events that may have a connection with the incident"
    )
    llmUsage: Optional[LlmUsageData] = Field(
        None, description="LLM usage and estimated cost metadata"
    )
    requestLatencyMs: Optional[float] = Field(
        None, description="End-to-end latency for generating the incident details"
    )


class DetailsResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "incidents": [
                    {
                        "id": "INC000000000000",
                        "shortDescription": "An increase of cpu was observed due to a high number of requests to the path /endpoint",
                        "description": "The tasks from ECS of the service billing-api were increasing CPU usage due to high requests.",
                        "resolutionSuggestions": [],
                        "relatedLogIds": ["transactionId1", "transactionId2"],
                    }
                ]
            }
        }
    )
    
    incidents: List[IncidentData] = Field(
        default_factory=list, description="List with incident details"
    )


class ErrorResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "message": "Invalid request payload",
                "code": "BAD_REQUEST",
                "details": ["incidentIds is required"],
            }
        }
    )
    
    message: str = Field(..., description="Error message")
    code: Optional[str] = Field(None, description="Error code")
    details: Optional[List[str]] = Field(None, description="Additional error details")
