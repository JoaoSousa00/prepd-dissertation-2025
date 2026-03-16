package isep.smartalarms.presentation.dto.request;

import io.swagger.v3.oas.annotations.media.Schema;

import java.util.List;

public record DetailsRequest(
        @Schema(description = "List of incident identifiers", examples = {"INC000000000000", "INC000000000001"})
        List<String> incidentIds) {
}
