from src.application.incident_details import IncidentDetailsService
from src.application.incident_fetching import IncidentFetchingService
from src.domain.incident import BaseIncident
from src.domain.llm import (
    IncidentEnrichment,
    LlmGatewayUnavailableError,
    LlmSummary,
    LlmUsage,
    MitigationSuggestion,
)
from src.shared.observability import RequestLogContext, bind_request_context, get_current_request_context


class FakeIncidentSource:
    def __init__(self, incidents=None, same_title_incidents=None, fallback_incidents=None):
        self._incidents = incidents or {}
        self._same_title_incidents = same_title_incidents or []
        self._fallback_incidents = fallback_incidents or []
        self.same_title_limits = []
        self.fallback_limits = []
        self.fallback_groups = []

    def fetch_base_incident(self, incident_id):
        return self._incidents.get(incident_id)

    def fetch_same_title_incidents(self, short_description, limit=None):
        self.same_title_limits.append(limit)
        return list(self._same_title_incidents)

    def fetch_recent_assignment_group_incidents(self, assignment_group, limit=None):
        self.fallback_groups.append(assignment_group)
        self.fallback_limits.append(limit)
        return list(self._fallback_incidents)


class SuccessfulLlmGateway:
    def enrich_incident(self, incident_id, short_description, description, max_tokens=None, **kwargs):
        return IncidentEnrichment(
            summary=LlmSummary(text=f"Summary for {incident_id}"),
            related_incidents=["INC0002", "INC0002", "INC0003"],
            mitigation_suggestions=[
                MitigationSuggestion(
                    confidence="evidence-based",
                    investigation="Check service health.",
                    mitigation="Restart service.",
                    resolution_note="Service restarted and healthy.",
                    related_incidents=["INC0002"],
                )
            ],
            usage=LlmUsage(
                model="openai/gpt-5",
                tokens_in=100,
                tokens_out=25,
                tokens_total=125,
                estimated_cost=0.0125,
            ),
        )


class FailingLlmGateway:
    def enrich_incident(self, incident_id, short_description, description, max_tokens=None, **kwargs):
        raise LlmGatewayUnavailableError("gateway unavailable")


class CapturingLlmGateway:
    def __init__(self):
        self.kwargs = None

    def enrich_incident(self, incident_id, short_description, description, max_tokens=None, **kwargs):
        self.kwargs = kwargs
        return IncidentEnrichment(summary=LlmSummary(text=f"Summary for {incident_id}"))


def test_fetch_incident_details_without_llm_returns_base_incidents():
    service = IncidentDetailsService(
        IncidentFetchingService(
            FakeIncidentSource(
                incidents={
                    "INC0001": BaseIncident(
                        id="INC0001",
                        short_description="API latency spike",
                        description="Requests slowed down during load peak.",
                    )
                }
            )
        )
    )

    details = service.fetch_incident_details(["INC0001"])

    assert len(details) == 1
    assert details[0].id == "INC0001"
    assert details[0].summary is None
    assert details[0].resolution_suggestions == []
    assert details[0].related_incidents == []


def test_fetch_incident_details_with_llm_adds_enrichment_fields():
    service = IncidentDetailsService(
        incident_fetching_service=IncidentFetchingService(
            FakeIncidentSource(
                incidents={
                    "INC0001": BaseIncident(
                        id="INC0001",
                        short_description="API latency spike",
                        description="Requests slowed down during load peak.",
                    )
                }
            )
        ),
        llm_gateway=SuccessfulLlmGateway(),
    )

    details = service.fetch_incident_details(["INC0001"])

    assert len(details) == 1
    assert details[0].summary == "Summary for INC0001"
    assert details[0].related_incidents == ["INC0002", "INC0003"]
    assert len(details[0].resolution_suggestions) == 1
    assert details[0].resolution_suggestions[0].confidence == "evidence-based"
    assert details[0].resolution_suggestions[0].investigation == "Check service health."
    assert details[0].resolution_suggestions[0].mitigation == "Restart service."
    assert details[0].resolution_suggestions[0].resolution_note == "Service restarted and healthy."
    assert details[0].llm_usage is not None
    assert details[0].llm_usage.tokens_total == 125
    assert details[0].request_latency_ms is not None


def test_fetch_incident_details_with_failing_llm_returns_base_data():
    service = IncidentDetailsService(
        incident_fetching_service=IncidentFetchingService(
            FakeIncidentSource(
                incidents={
                    "INC0001": BaseIncident(
                        id="INC0001",
                        short_description="API latency spike",
                        description="Requests slowed down during load peak.",
                    )
                }
            )
        ),
        llm_gateway=FailingLlmGateway(),
    )

    details = service.fetch_incident_details(["INC0001"])

    assert len(details) == 1
    assert details[0].id == "INC0001"
    assert details[0].summary is None
    assert details[0].resolution_suggestions == []


def test_fetch_incident_details_does_not_double_count_suggestions():
    service = IncidentDetailsService(
        incident_fetching_service=IncidentFetchingService(
            FakeIncidentSource(
                incidents={
                    "INC0001": BaseIncident(
                        id="INC0001",
                        short_description="API latency spike",
                        description="Requests slowed down during load peak.",
                    ),
                    "INC0002": BaseIncident(
                        id="INC0002",
                        short_description="DB latency spike",
                        description="Database queries are slow.",
                    ),
                }
            )
        ),
        llm_gateway=SuccessfulLlmGateway(),
    )

    with bind_request_context(RequestLogContext(request_id="req-dup")):
        details = service.fetch_incident_details(["INC0001", "INC0002"])
        payload = get_current_request_context().build_summary_payload()

    assert len(details) == 2
    assert payload["itsm_summary"]["suggestions_number"] == 2


def test_fetch_incident_details_passes_sanitized_main_incident_context_to_llm():
    gateway = CapturingLlmGateway()
    service = IncidentDetailsService(
        incident_fetching_service=IncidentFetchingService(
            FakeIncidentSource(
                incidents={
                    "INC0001": BaseIncident(
                        id="INC0001",
                        short_description="API latency spike",
                        description="Requests slowed down during load peak.",
                        raw={
                            "number": "INC0001",
                            "short_description": "API latency spike",
                            "description": "Requests slowed down during load peak.",
                            "state": "New",
                            "priority": "3 - Moderate",
                            "impact": "2 - Medium",
                            "urgency": "2 - Medium",
                            "assignment_group": {"name": "Ops"},
                            "caller_id": {"name": "Hidden Caller"},
                            "assigned_to": {"name": "Hidden Assignee"},
                            "resolved_by": {"name": "Hidden Resolver"},
                            "attachments": [{"name": "secret.txt"}],
                            "comments": ["comment-1"],
                            "work_notes": ["work-note-1"],
                            "ci_item": [{"name": "Service"}],
                        },
                    )
                }
            )
        ),
        llm_gateway=gateway,
    )

    service.fetch_incident_details(["INC0001"])

    context = gateway.kwargs["main_incident_context"]
    assert "number: INC0001" in context
    assert "short_description: API latency spike" in context
    assert "description: Requests slowed down during load peak." in context
    assert "state: New" in context
    assert "priority: 3 - Moderate" in context
    assert "impact: 2 - Medium" in context
    assert "urgency: 2 - Medium" in context
    assert "assignment_group" in context
    assert "ci_item" in context
    assert "caller_id" not in context
    assert "assigned_to" not in context
    assert "resolved_by" not in context
    assert "attachments" not in context


def test_fetch_incident_details_uses_same_title_fetch_limit_and_recent_resolved_at_filter(monkeypatch):
    gateway = CapturingLlmGateway()
    source = FakeIncidentSource(
        incidents={
            "INC0001": BaseIncident(
                id="INC0001",
                number="INC0001",
                short_description="API latency spike",
                description="Requests slowed down during load peak.",
            )
        },
        same_title_incidents=[
            BaseIncident(id="INC0001", number="INC0001", short_description="API latency spike", resolved_at="2026-09-05T10:00:00Z"),
            BaseIncident(id="INC1001", number="INC1001", short_description="API latency spike", resolved_at="2026-09-05T08:00:00Z"),
            BaseIncident(id="INC1002", number="INC1002", short_description="API latency spike", resolved_at="2026-09-05T11:00:00Z"),
            BaseIncident(id="INC1003", number="INC1003", short_description="API latency spike", resolved_at="2026-09-04T11:00:00Z"),
        ],
    )
    service = IncidentDetailsService(
        incident_fetching_service=IncidentFetchingService(source),
        llm_gateway=gateway,
    )

    monkeypatch.setenv("RELATED_INCIDENTS_MAX_SAME_TITLE", "100")
    monkeypatch.setenv("RELATED_INCIDENTS_RECENT_SAME_TITLE_LIMIT", "2")
    with bind_request_context(RequestLogContext(request_id="req-title-count")):
        service.fetch_incident_details(["INC0001"])
        payload = get_current_request_context().build_summary_payload()

    assert source.same_title_limits == [100]
    assert payload["itsm_summary"]["total_incidents_title"] == 3
    assert payload["itsm_summary"]["total_incidents_fallback"] == 0
    same_title_context = gateway.kwargs["same_title_incident_context"]
    assert "Incident INC0001" not in same_title_context
    assert "Incident INC1002" in same_title_context


def test_fetch_incident_details_excludes_explicit_related_from_same_title_before_recency_limit(monkeypatch):
    gateway = CapturingLlmGateway()
    source = FakeIncidentSource(
        incidents={
            "INC0001": BaseIncident(
                id="INC0001",
                number="INC0001",
                short_description="API latency spike",
                description="Issue references INC1002 as a known related incident.",
                raw={
                    "description": "Issue references INC1002 as a known related incident.",
                },
            )
        },
        same_title_incidents=[
            BaseIncident(id="INC1002", number="INC1002", short_description="API latency spike", resolved_at="2026-09-05T12:00:00Z"),
            BaseIncident(id="INC1001", number="INC1001", short_description="API latency spike", resolved_at="2026-09-05T11:00:00Z"),
            BaseIncident(id="INC1003", number="INC1003", short_description="API latency spike", resolved_at="2026-09-05T10:00:00Z"),
        ],
    )
    service = IncidentDetailsService(
        incident_fetching_service=IncidentFetchingService(source),
        llm_gateway=gateway,
    )

    monkeypatch.setenv("RELATED_INCIDENTS_RECENT_SAME_TITLE_LIMIT", "2")
    service.fetch_incident_details(["INC0001"])

    same_title_context = gateway.kwargs["same_title_incident_context"]
    assert "Incident INC1002" not in same_title_context
    assert "Incident INC1001" in same_title_context
    assert "Incident INC1003" in same_title_context


def test_fetch_incident_details_uses_assignment_group_fallback_when_same_title_is_empty(monkeypatch):
    gateway = CapturingLlmGateway()
    source = FakeIncidentSource(
        incidents={
            "INC0001": BaseIncident(
                id="INC0001",
                number="INC0001",
                short_description="API latency spike",
                description="Requests slowed down during load peak.",
                raw={
                    "number": "INC0001",
                    "assignment_group": {"name": "FT_LOS-CTW-Force-Devopsteam"},
                },
            )
        },
        fallback_incidents=[
            BaseIncident(id="INC0099", number="INC0099", short_description="Database errors", resolved_at="2026-09-05T12:00:00Z"),
            BaseIncident(id="INC0001", number="INC0001", short_description="API latency spike", resolved_at="2026-09-05T11:00:00Z"),
            BaseIncident(id="INC0100", number="INC0100", short_description="Queue backlog", resolved_at="2026-09-05T09:00:00Z"),
        ],
    )
    service = IncidentDetailsService(
        incident_fetching_service=IncidentFetchingService(source),
        llm_gateway=gateway,
    )

    monkeypatch.setenv("RELATED_INCIDENTS_MAX_SAME_TITLE", "100")
    monkeypatch.setenv("RELATED_INCIDENTS_FALLBACK_FETCH_LIMIT", "50")
    monkeypatch.setenv("RELATED_INCIDENTS_FALLBACK_RECENT_LIMIT", "2")

    with bind_request_context(RequestLogContext(request_id="req-fallback")):
        service.fetch_incident_details(["INC0001"])
        payload = get_current_request_context().build_summary_payload()

    assert source.fallback_groups == ["FT_LOS-CTW-Force-Devopsteam"]
    assert source.fallback_limits == [50]
    assert payload["itsm_summary"]["fallback_triggered"] is True
    assert payload["itsm_summary"]["total_incidents_fallback"] == 2
    assert payload["itsm_summary"]["fallback_kept_incidents"] == 2
    assert payload["itsm_summary"]["fetched_incidents_by_title"] == []
    fallback_context = gateway.kwargs["same_title_incident_context"]
    assert "not proven related incidents" in fallback_context
    assert "Incident INC0099" in fallback_context
    assert "Incident INC0001" not in fallback_context
