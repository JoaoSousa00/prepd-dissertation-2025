package isep.smartalarms.presentation.dto.response;

import io.swagger.v3.oas.annotations.media.Schema;

import java.util.List;

public record DetailsResponse(
        @Schema(description = "List with incidents details")
        List<IncidentData> incidents) {
}
