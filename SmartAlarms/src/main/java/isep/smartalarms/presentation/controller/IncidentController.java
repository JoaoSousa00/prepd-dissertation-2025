package isep.smartalarms.presentation.controller;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.media.Schema;
import io.swagger.v3.oas.annotations.tags.Tag;
import isep.smartalarms.presentation.dto.request.DetailsRequest;
import isep.smartalarms.presentation.dto.response.DetailsResponse;
import lombok.RequiredArgsConstructor;
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
    @Operation(summary = "Fetches details of incidents")
    public ResponseEntity<DetailsResponse> details(DetailsRequest detailsRequest,
                                                   @RequestHeader Map<String, String> headers) {
        return new ResponseEntity<>(HttpStatus.OK);
    }
}
