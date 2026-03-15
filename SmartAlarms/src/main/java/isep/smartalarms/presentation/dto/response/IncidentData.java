package isep.smartalarms.presentation.dto.response;

import java.util.List;

public record IncidentData(String id,
                           String shortDescription,
                           String description,
                           List<String> resolutionSuggestions,
                           List<String> relatedLogIds) {
}
