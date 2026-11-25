package io.github.iy88.project1.api.category;

import io.github.iy88.project1.api.account.CurrentAccount;
import io.github.iy88.project1.category.application.BannedScopeService;
import jakarta.servlet.http.HttpServletRequest;
import java.util.List;
import org.springframework.context.annotation.Profile;
import org.springframework.http.CacheControl;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
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

    @PostMapping("/api/v1/admin/banned-items")
    ResponseEntity<BannedScopeService.ItemMutation> create(@RequestBody ItemRequest body,
                                                           HttpServletRequest request) {
        var manager = CategoryController.manager(current, request);
        return ResponseEntity.status(201).cacheControl(CacheControl.noStore())
                .body(banned.create(manager.account().id(), body.item()));
    }

    @PatchMapping("/api/v1/admin/banned-items/{itemId}")
    ResponseEntity<BannedScopeService.ItemMutation> update(@PathVariable String itemId,
                                                           @RequestBody ItemRequest body,
                                                           HttpServletRequest request) {
        var manager = CategoryController.manager(current, request);
        return ResponseEntity.ok().cacheControl(CacheControl.noStore())
                .body(banned.update(manager.account().id(), id(itemId), body.item()));
    }

    @DeleteMapping("/api/v1/admin/banned-items/{itemId}")
    ResponseEntity<BannedScopeService.ScopeMutation> delete(@PathVariable String itemId,
                                                            HttpServletRequest request) {
        CategoryController.manager(current, request);
        return ResponseEntity.ok().cacheControl(CacheControl.noStore())
                .body(banned.delete(id(itemId)));
    }

    record BannedScopeRequest(List<BannedScopeService.Input> items) {
    }

    record ItemRequest(String group, String content, Integer displayOrder) {
        BannedScopeService.ItemInput item() {
            return new BannedScopeService.ItemInput(group, content, displayOrder);
        }
    }

    private static long id(String value) {
        try {
            long id = Long.parseLong(value);
            if (id > 0) {
                return id;
            }
        } catch (NumberFormatException ignored) {
            // Fall through to the shared invalid identifier error.
        }
        throw new io.github.iy88.project1.core.BusinessError("INPUT_INVALID", 422, "禁发条目标识无效");
    }
}
