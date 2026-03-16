package isep.smartalarms.presentation.controller;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.media.Content;
import io.swagger.v3.oas.annotations.media.Schema;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.tags.Tag;
import isep.smartalarms.presentation.dto.request.DetailsRequest;
import isep.smartalarms.presentation.dto.response.DetailsResponse;
import lombok.RequiredArgsConstructor;
import org.springdoc.core.annotations.ParameterObject;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;

import java.util.Map;

@Controller
@RequestMapping("/incident")
@RequiredArgsConstructor
@Tag(name = "Incidents")
public class IncidentController {

    @GetMapping("/details")
    @Operation(summary = "Fetches details of specified incidents",
            description = "Returns additional information from related incidents and log events for a list of incidents.")
    @ApiResponse(responseCode = "200",
            description = "Successful search containing more than zero results",
            content = @Content(mediaType = "application/json", schema = @Schema(implementation = DetailsResponse.class)))
    @ApiResponse(responseCode = "204",
            description = "The requested incidents were not found",
            content = @Content(mediaType = "application/json"))
    @ApiResponse(responseCode = "400",
            description = "The incoming request did not pass input validation. The response will explain more details on root cause of the error",
            content = @Content(mediaType = "application/json"))
    @ApiResponse(responseCode = "401",
            description = "Unauthorized",
            content = @Content(mediaType = "application/json"))
    @ApiResponse(responseCode = "500",
            description = "Internal Server Error",
            content = @Content(mediaType = "application/json"))
    public ResponseEntity<DetailsResponse> details(@ParameterObject DetailsRequest detailsRequest,
                                                   @RequestHeader Map<String, String> headers) {
        return new ResponseEntity<>(HttpStatus.OK);
    }
}
