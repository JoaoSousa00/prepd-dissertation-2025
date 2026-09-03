import pytest

from src.application.incident_fetching import IncidentFetchingService
from src.domain.incident import (
    BaseIncident,
    IncidentSourceUnauthorizedError,
    IncidentSourceUnavailableError,
)


class FakeIncidentSource:
    def __init__(self, incidents=None, failing_ids=None, unauthorized_ids=None):
        self._incidents = incidents or {}
        self._failing_ids = set(failing_ids or [])
        self._unauthorized_ids = set(unauthorized_ids or [])
        self.calls = []

    def fetch_base_incident(self, incident_id):
        self.calls.append(incident_id)
        if incident_id in self._unauthorized_ids:
            raise IncidentSourceUnauthorizedError("missing credentials")
        if incident_id in self._failing_ids:
            raise IncidentSourceUnavailableError("incident source unavailable")
        return self._incidents.get(incident_id)


def test_fetch_base_incidents_returns_found_records():
    service = IncidentFetchingService(
        FakeIncidentSource(
            incidents={
                "INC000000000001": BaseIncident(
                    id="INC000000000001",
                    short_description="Billing API latency spike",
                    description="Billing API requests exceeded the expected latency threshold.",
                )
            }
        )
    )

    incidents = service.fetch_base_incidents(["INC000000000001"])

    assert incidents == [
        BaseIncident(
            id="INC000000000001",
            short_description="Billing API latency spike",
            description="Billing API requests exceeded the expected latency threshold.",
        )
    ]


def test_fetch_base_incidents_skips_missing_records():
    service = IncidentFetchingService(
        FakeIncidentSource(
            incidents={
                "INC000000000001": BaseIncident(
                    id="INC000000000001",
                    short_description="Billing API latency spike",
                    description="Billing API requests exceeded the expected latency threshold.",
                ),
                "INC000000000002": BaseIncident(
                    id="INC000000000002",
                    short_description="Checkout timeout surge",
                    description="Checkout requests timed out while calling downstream services.",
                ),
            }
        )
    )

    incidents = service.fetch_base_incidents(
        ["INC000000000001", "INC999999999999", "INC000000000002"]
    )

    assert incidents == [
        BaseIncident(
            id="INC000000000001",
            short_description="Billing API latency spike",
            description="Billing API requests exceeded the expected latency threshold.",
        ),
        BaseIncident(
            id="INC000000000002",
            short_description="Checkout timeout surge",
            description="Checkout requests timed out while calling downstream services.",
        ),
    ]


def test_fetch_base_incidents_continues_when_source_is_unavailable():
    service = IncidentFetchingService(
        FakeIncidentSource(
            incidents={
                "INC000000000001": BaseIncident(
                    id="INC000000000001",
                    short_description="Billing API latency spike",
                    description="Billing API requests exceeded the expected latency threshold.",
                ),
                "INC000000000003": BaseIncident(
                    id="INC000000000003",
                    short_description="Worker queue backlog",
                    description="Background workers accumulated a queue backlog after traffic increased.",
                ),
            },
            failing_ids={"INC000000000002"},
        )
    )

    incidents = service.fetch_base_incidents(
        ["INC000000000001", "INC000000000002", "INC000000000003"]
    )

    assert incidents == [
        BaseIncident(
            id="INC000000000001",
            short_description="Billing API latency spike",
            description="Billing API requests exceeded the expected latency threshold.",
        ),
        BaseIncident(
            id="INC000000000003",
            short_description="Worker queue backlog",
            description="Background workers accumulated a queue backlog after traffic increased.",
        ),
    ]


def test_fetch_base_incidents_propagates_unauthorized_error():
    service = IncidentFetchingService(
        FakeIncidentSource(unauthorized_ids={"INC000000000001"})
    )

    with pytest.raises(IncidentSourceUnauthorizedError):
        service.fetch_base_incidents(["INC000000000001"])


def test_fetch_base_incidents_deduplicates_incident_ids():
    source = FakeIncidentSource(
        incidents={
            "INC000000000001": BaseIncident(
                id="INC000000000001",
                short_description="Billing API latency spike",
                description="Billing API requests exceeded the expected latency threshold.",
            )
        }
    )
    service = IncidentFetchingService(source)

    incidents = service.fetch_base_incidents(
        ["INC000000000001", "INC000000000001", "INC000000000001"]
    )

    assert len(incidents) == 1
    assert source.calls == ["INC000000000001"]
