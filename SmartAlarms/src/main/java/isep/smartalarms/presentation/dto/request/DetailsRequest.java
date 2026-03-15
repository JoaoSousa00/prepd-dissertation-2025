package isep.smartalarms.presentation.dto.request;

import io.swagger.v3.oas.annotations.media.Schema;

import java.util.List;

public record DetailsRequest(
        @Schema(description = "incidents", example = "INC00000000")
        List<String> incidentIds) {

    //TODO Domingo: Criar controller e ver como gerar swagger
}
