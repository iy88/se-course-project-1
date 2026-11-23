package io.github.iy88.project1.api.category;

import io.github.iy88.project1.api.account.CurrentAccount;
import io.github.iy88.project1.category.application.BannedScopeService;
import jakarta.servlet.http.HttpServletRequest;
import java.util.List;
import org.springframework.context.annotation.Profile;
import org.springframework.http.CacheControl;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@Profile("infrastructure")
class BannedScopeController {
    private final BannedScopeService banned;
    private final CurrentAccount current;

    BannedScopeController(BannedScopeService banned, CurrentAccount current) {
        this.banned = banned;
        this.current = current;
    }

    @GetMapping("/api/v1/banned-items")
    ResponseEntity<BannedScopeService.BannedScopeView> view(HttpServletRequest request) {
        current.require(request);
        return ResponseEntity.ok().cacheControl(CacheControl.noStore()).body(banned.view());
    }

    @PutMapping("/api/v1/admin/banned-items")
    ResponseEntity<BannedScopeService.BannedScopeView> replace(@RequestBody BannedScopeRequest body,
                                                                HttpServletRequest request) {
        var manager = CategoryController.manager(current, request);
        return ResponseEntity.ok().cacheControl(CacheControl.noStore())
                .body(banned.replace(manager.account().id(), body.items()));
    }

    record BannedScopeRequest(List<BannedScopeService.Input> items) {
    }
}
