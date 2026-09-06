import logging
import os
import re
import json
import time
from datetime import UTC, datetime
from typing import Iterable, List, Optional

from src.domain.incident_fetching import IncidentFetchingService
from src.domain.incident import BaseIncident, IncidentDetails, ResolutionSuggestion
from src.domain.llm import LlmGateway, LlmGatewayError
from src.shared.observability import bind_request_context, get_current_request_context, log_request_summary

logger = logging.getLogger(__name__)
DEFAULT_RELATED_INCIDENTS_MAX_SAME_TITLE = 100
DEFAULT_RELATED_INCIDENTS_RECENT_SAME_TITLE_LIMIT = 10
_TRUTHY_VALUES = {"1", "true", "yes", "on"}


class IncidentDetailsService:
    def __init__(
        self,
        incident_fetching_service: IncidentFetchingService,
        llm_gateway: Optional[LlmGateway] = None,
    ):
        self._incident_fetching_service = incident_fetching_service
        self._llm_gateway = llm_gateway

    def fetch_incident_details(self, incident_ids: Iterable[str]) -> List[IncidentDetails]:
        context = get_current_request_context()
        if context is None:
            with bind_request_context():
                return self._fetch_incident_details(incident_ids, emit_summary=True)
        return self._fetch_incident_details(incident_ids, emit_summary=False)

    def _fetch_incident_details(self, incident_ids: Iterable[str], emit_summary: bool = False) -> List[IncidentDetails]:
        context = get_current_request_context()
        seen_ids: set[str] = set()
        ordered_ids: list[str] = []
        for value in incident_ids:
            normalized = value.strip() if value else ""
            if not normalized or normalized in seen_ids:
                continue
            seen_ids.add(normalized)
            ordered_ids.append(normalized)
        if context is not None and ordered_ids:
            context.main_incident = context.main_incident or ordered_ids[0]

        base_incidents = self._incident_fetching_service.fetch_base_incidents(ordered_ids)
        details: List[IncidentDetails] = []

        for incident in base_incidents:
            started_at = time.perf_counter()
            detail = IncidentDetails(
                id=incident.id,
                short_description=incident.short_description,
                description=incident.description,
            )

            related_context = self._build_context_snapshot(incident)
            main_incident_context = self._build_main_incident_context(incident)
            if self._llm_gateway is not None:
                try:
                    try:
                        enrichment = self._llm_gateway.enrich_incident(
                            incident_id=incident.id,
                            short_description=incident.short_description,
                            description=incident.description,
                            main_incident_context=main_incident_context,
                            related_incident_context=related_context["related_incident_context"],
                            same_title_incident_context=related_context["same_title_incident_context"],
                            use_fallback_prompt=bool(context and context.fallback_triggered),
                        )
                    except TypeError:
                        enrichment = self._llm_gateway.enrich_incident(
                            incident_id=incident.id,
                            short_description=incident.short_description,
                            description=incident.description,
                        )
                except LlmGatewayError as exc:
                    logger.warning(
                        "Skipping LLM enrichment for incident %s: %s",
                        incident.id,
                        exc,
                    )
                    if context is not None:
                        context.record_llm_error(str(exc), 500)
                else:
                    detail.summary = enrichment.summary.text if enrichment.summary else None
                    detail.related_incidents = list(dict.fromkeys(enrichment.related_incidents))
                    detail.resolution_suggestions = [
                        ResolutionSuggestion(
                            confidence=suggestion.confidence,
                            investigation=suggestion.investigation,
                            mitigation=suggestion.mitigation,
                            resolution_note=suggestion.resolution_note,
                            related_incidents=suggestion.related_incidents,
                        )
                        for suggestion in enrichment.mitigation_suggestions
                    ]
                    detail.llm_usage = enrichment.usage
                    if context is not None and enrichment.usage is not None:
                        context.record_llm_usage(
                            tokens_in=enrichment.usage.tokens_in,
                            tokens_out=enrichment.usage.tokens_out,
                            cost_usd=enrichment.usage.estimated_cost,
                        )
            detail.request_latency_ms = (time.perf_counter() - started_at) * 1000
            details.append(detail)

        if context is not None:
            context.suggestions_number += sum(len(item.resolution_suggestions) for item in details)
            context.latency_ms = (
                context.latency_ms
                if context.latency_ms is not None
                else sum(item.request_latency_ms or 0 for item in details)
            )
            context.summary_completed = bool(details)

        if emit_summary:
            log_request_summary()
        return details

    def _build_context_snapshot(self, incident: BaseIncident) -> dict[str, str]:
        related_numbers = self._discover_related_numbers(incident)
        same_title_recent_limit = max(
            1,
            int(
                os.getenv(
                    "RELATED_INCIDENTS_RECENT_SAME_TITLE_LIMIT",
                    str(DEFAULT_RELATED_INCIDENTS_RECENT_SAME_TITLE_LIMIT),
                )
            ),
        )
        fallback_recent_limit = max(
            1,
            int(
                os.getenv(
                    "RELATED_INCIDENTS_FALLBACK_RECENT_LIMIT",
                    "10",
                )
            ),
        )
        same_title_incidents = []
        if incident.short_description:
            same_title_limit = max(
                1,
                int(os.getenv("RELATED_INCIDENTS_MAX_SAME_TITLE", str(DEFAULT_RELATED_INCIDENTS_MAX_SAME_TITLE))),
            )
            same_title_incidents = self._incident_fetching_service.fetch_same_title_incidents(
                incident.short_description,
                limit=same_title_limit,
            )

        main_incident_ids = {incident.id.upper()}
        if incident.number:
            main_incident_ids.add(incident.number.upper())
        related_ids = {
            related_id.upper()
            for related_id in related_numbers
            if related_id and related_id.strip()
        }
        context = get_current_request_context()
        if context is not None:
            total_without_main = sum(
                1
                for candidate in same_title_incidents
                if (candidate.number or candidate.id).upper() not in main_incident_ids
            )
            context.record_total_incidents_title(total_without_main)
            context.fallback_triggered = False
            context.fallback_kept_incidents = 0
            context.fetched_incidents_by_title = []

        title_candidates = self._dedupe_context_incidents(
            same_title_incidents,
            main_incident_ids,
            excluded_incident_ids=related_ids,
        )
        if context is not None and not context.fallback_triggered:
            context.fetched_incidents_by_title = [
                (candidate.number or candidate.id).upper()
                for candidate in title_candidates
                if (candidate.number or candidate.id).upper() not in main_incident_ids
            ]

        deduped_same_title = sorted(
            title_candidates,
            key=self._incident_resolved_at_sort_key,
            reverse=True,
        )[:same_title_recent_limit]

        if not deduped_same_title and incident.raw is not None:
            assignment_group = self._extract_assignment_group(incident)
            if assignment_group:
                fallback_limit = max(
                    1,
                    int(os.getenv("RELATED_INCIDENTS_FALLBACK_FETCH_LIMIT", "100")),
                )
                fallback_incidents = self._incident_fetching_service.fetch_recent_assignment_group_incidents(
                    assignment_group,
                    limit=fallback_limit,
                )
                deduped_fallback = self._dedupe_context_incidents(fallback_incidents, main_incident_ids)
                deduped_fallback = sorted(
                    deduped_fallback,
                    key=self._incident_resolved_at_sort_key,
                    reverse=True,
                )[:fallback_recent_limit]
                if context is not None:
                    context.fallback_triggered = True
                    context.fallback_kept_incidents = len(deduped_fallback)
                    context.fetched_incidents_by_title = []
                    total_without_main = sum(
                        1
                        for candidate in fallback_incidents
                        if (candidate.number or candidate.id).upper() not in main_incident_ids
                    )
                    context.record_total_incidents_fallback(total_without_main)
                deduped_same_title = deduped_fallback

        if context is not None and not context.fallback_triggered:
            context.record_total_incidents_fallback(0)

        deduped_related = []
        seen_related: set[str] = set()
        for incident_id in related_numbers:
            if incident_id.upper() in seen_related or incident_id.upper() == incident.id.upper():
                continue
            seen_related.add(incident_id.upper())
            deduped_related.append(incident_id)
        if deduped_related:
            fetched_related = self._incident_fetching_service.fetch_related_incident_details(deduped_related)
            related_summary = self._summarize_incidents(fetched_related or [])
        else:
            related_summary = "No related incidents were explicitly referenced in the main incident."
        same_title_summary = self._summarize_incidents(deduped_same_title)
        if context is not None and context.fallback_triggered and deduped_same_title:
            same_title_summary = (
                "Recent assignment-group incidents (not proven related incidents; recent team context only):\n"
                + same_title_summary
            )
        return {
            "related_incident_context": related_summary,
            "same_title_incident_context": same_title_summary,
        }

    @staticmethod
    def _dedupe_context_incidents(
        incidents: list[BaseIncident],
        main_incident_ids: set[str],
        excluded_incident_ids: Optional[set[str]] = None,
    ) -> list[BaseIncident]:
        deduped: list[BaseIncident] = []
        seen_numbers: set[str] = set()
        excluded_numbers = excluded_incident_ids or set()
        for candidate in incidents:
            candidate_number = (candidate.number or candidate.id).upper()
            if (
                candidate_number in main_incident_ids
                or candidate_number in excluded_numbers
                or candidate_number in seen_numbers
            ):
                continue
            seen_numbers.add(candidate_number)
            deduped.append(candidate)
        return deduped

    @staticmethod
    def _extract_assignment_group(incident: BaseIncident) -> str:
        payload = incident.raw or {}
        if not isinstance(payload, dict):
            return ""
        for key in ("assignment_group", "assignmentGroup"):
            value = payload.get(key)
            if isinstance(value, dict):
                for nested_key in ("name", "display_value", "value"):
                    candidate = value.get(nested_key)
                    if candidate:
                        return str(candidate).strip()
            elif isinstance(value, str):
                candidate = value.strip()
                if candidate:
                    return candidate
        return ""

    @staticmethod
    def _build_main_incident_context(incident: BaseIncident) -> str:
        include_comments = IncidentDetailsService._include_related_incident_comments()
        include_work_notes = IncidentDetailsService._include_related_incident_work_notes()
        excluded_keys = {
            "caller_id",
            "assigned_to",
            "resolved_by",
            "attachments",
            "attachment",
            "close_notes",
            "closed_at",
            "close_code",
        }
        if not include_comments:
            excluded_keys.add("comments")
        if not include_work_notes:
            excluded_keys.add("work_notes")
        payload: dict[str, object] = {}
        if isinstance(incident.raw, dict) and incident.raw:
            payload.update(incident.raw)
        payload.setdefault("number", incident.number or incident.id)
        payload.setdefault("short_description", incident.short_description)
        payload.setdefault("description", incident.description)
        payload.setdefault("state", incident.state)
        payload.setdefault("resolved_at", incident.resolved_at)
        payload.setdefault("close_notes", incident.close_notes)
        payload.setdefault("closed_at", incident.closed_at)
        payload.setdefault("close_code", incident.close_code)
        payload.setdefault("hold_reason", incident.hold_reason)
        payload.setdefault("comments", incident.comments)
        payload.setdefault("work_notes", incident.work_notes)

        lines = ["Main incident fields:"]
        for key, value in payload.items():
            if key in excluded_keys or value in (None, "", [], {}):
                continue
            lines.append(f"- {key}: {IncidentDetailsService._format_context_value(value)}")
        return "\n".join(lines)

    @staticmethod
    def _discover_related_numbers(incident: BaseIncident) -> list[str]:
        payload = incident.raw or {}
        text_values: list[str] = []
        if isinstance(payload, dict):
            for key in ("parent_incident", "description", "close_notes", "comments", "work_notes", "hold_reason"):
                value = payload.get(key)
                if value is None:
                    continue
                if isinstance(value, list):
                    text_values.extend(str(part) for part in value)
                elif isinstance(value, dict):
                    text_values.append(str(value.get("number") or value.get("value") or value.get("sys_id") or value))
                else:
                    text_values.append(str(value))
        matches = []
        for text in text_values:
            matches.extend(re.findall(r"INC[0-9]+", text, flags=re.IGNORECASE))
        normalized = [match.upper() for match in matches]
        if incident.id:
            normalized = [value for value in normalized if value.upper() != incident.id.upper()]
        return list(dict.fromkeys(normalized))

    @staticmethod
    def _summarize_incidents(incidents: List[BaseIncident]) -> str:
        if not incidents:
            return "No historical incidents were available for this context."
        include_comments = IncidentDetailsService._include_related_incident_comments()
        include_work_notes = IncidentDetailsService._include_related_incident_work_notes()
        lines = []
        for incident in incidents:
            summary = [
                f"Incident {incident.id}",
                f"short_description={incident.short_description or 'N/A'}",
            ]
            if incident.state:
                summary.append(f"state={incident.state}")
            if incident.resolved_at:
                summary.append(f"resolved_at={incident.resolved_at}")
            if incident.closed_at:
                summary.append(f"closed_at={incident.closed_at}")
            if incident.close_notes:
                summary.append(f"close_notes={incident.close_notes}")
            if incident.description:
                summary.append(f"description={incident.description}")
            if incident.hold_reason:
                summary.append(f"hold_reason={incident.hold_reason}")
            if incident.close_code:
                summary.append(f"close_code={incident.close_code}")
            if include_comments and incident.comments:
                summary.append(f"comments={'; '.join(incident.comments[:2])}")
            if include_work_notes and incident.work_notes:
                summary.append(f"work_notes={'; '.join(incident.work_notes[:2])}")
            lines.append(" | ".join(summary))
        return "\n".join(lines)

    @staticmethod
    def _format_context_value(value: object) -> str:
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=True)
        return str(value)

    @staticmethod
    def _include_related_incident_comments() -> bool:
        return os.getenv("RELATED_INCIDENTS_INCLUDE_COMMENTS", "true").strip().lower() in _TRUTHY_VALUES

    @staticmethod
    def _include_related_incident_work_notes() -> bool:
        return os.getenv("RELATED_INCIDENTS_INCLUDE_WORK_NOTES", "true").strip().lower() in _TRUTHY_VALUES

    @staticmethod
    def _incident_resolved_at_sort_key(incident: BaseIncident) -> tuple[int, datetime]:
        timestamp = incident.resolved_at or incident.closed_at
        if not timestamp:
            return (0, datetime.min.replace(tzinfo=UTC))
        normalized_timestamp = timestamp.strip()
        if normalized_timestamp.endswith("Z"):
            normalized_timestamp = normalized_timestamp[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(normalized_timestamp)
        except ValueError:
            return (0, datetime.min.replace(tzinfo=UTC))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return (1, parsed.astimezone(UTC))
