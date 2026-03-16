package isep.smartalarms.presentation.dto.response;

import io.swagger.v3.oas.annotations.media.Schema;

import java.util.List;

@Schema(description = "Contains additional information about an incident")
public record IncidentData(
        @Schema(description = "The unique incident identifier",
                example = "INC000000000000",
                requiredMode = Schema.RequiredMode.REQUIRED)
        String id,
        @Schema(description = "A small description of what the incident is about (What and How)",
                example = "An increase of cpu was observed due to a high number of requests to the path <endpoint>")
        String shortDescription,
        @Schema(description = "A more broad description with the context of the incident. It can refer to log events or related incidents if there is any connection.",
                example = "The tasks from ECS of the service <service> were increasing the cpu usage due to a high " +
                        "number of requests to the path <endpoint>. The last related incidents (INC000000000001 and " +
                        "INC000000000002) suggest to restart the tasks manually in the AWS Console.")
        String description,
        @Schema(description = "The list of ordered suggestions to mitigate the incident")
        List<ResolutionSuggestion> resolutionSuggestions,
        @Schema(description = "The list of log events that may have a connection with the incident",
                example = "[\"transactionId1\", \"transactionId2\"]")
        List<String> relatedLogIds) {
}
