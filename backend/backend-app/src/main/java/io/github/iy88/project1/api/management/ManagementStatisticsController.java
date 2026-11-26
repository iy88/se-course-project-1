package io.github.iy88.project1.api.management;

import io.github.iy88.project1.api.account.CurrentAccount;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.context.annotation.Profile;
import org.springframework.http.CacheControl;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/management")
@Profile("infrastructure & !dependency-probe & !file-probe")
class ManagementStatisticsController {
    private final CurrentAccount current;
    private final ManagementStatisticsQueries queries;

    ManagementStatisticsController(CurrentAccount current, ManagementStatisticsQueries queries) {
        this.current = current;
        this.queries = queries;
    }

    @GetMapping("/statistics")
    ResponseEntity<ManagementStatisticsQueries.Statistics> statistics(
            @RequestParam(name = "time_scope", required = false) String scope,
            @RequestParam(name = "start_at", required = false) String startAt,
            @RequestParam(name = "end_at", required = false) String endAt,
            HttpServletRequest request) {
        var identity = current.require(request);
        var result = queries.statistics(identity.account().id(), scope, startAt, endAt);
        return ResponseEntity.ok().cacheControl(CacheControl.noStore()).body(result);
    }
}
