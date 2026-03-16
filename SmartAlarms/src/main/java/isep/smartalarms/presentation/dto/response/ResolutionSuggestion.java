package isep.smartalarms.presentation.dto.response;

import io.swagger.v3.oas.annotations.media.Schema;

import java.util.List;

@Schema(description = "Information about a resolution suggestion and where it came from")
public record ResolutionSuggestion(
        @Schema(description = "The action that is suggested",
                example = "The ECS tasks should be restarted")
        String suggestion,
        @Schema(description = "The list of incidents that led to this suggestion",
                example = "[\"INC000000000001\", \"INC000000000002\"]")
        List<String> relatedIncidents,
        @Schema(description = "The list of log events that led to this suggestion",
                example = "[\"transactionId1\", \"transactionId2\"]")
        List<String> relatedLogIds) {
}
