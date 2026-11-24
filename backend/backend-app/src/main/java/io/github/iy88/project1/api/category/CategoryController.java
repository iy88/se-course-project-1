package io.github.iy88.project1.api.category;

import io.github.iy88.project1.account.application.SessionService;
import io.github.iy88.project1.api.account.CurrentAccount;
import io.github.iy88.project1.category.application.CategoryService;
import io.github.iy88.project1.core.BusinessError;
import jakarta.servlet.http.HttpServletRequest;
import java.util.List;
import org.springframework.context.annotation.Profile;
import org.springframework.http.CacheControl;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/categories")
@Profile("infrastructure")
class CategoryController {
    private final CategoryService categories;
    private final CurrentAccount current;

    CategoryController(CategoryService categories, CurrentAccount current) {
        this.categories = categories;
        this.current = current;
    }

    @GetMapping
    ResponseEntity<Items> list(HttpServletRequest request) {
        current.require(request);
        return ResponseEntity.ok().cacheControl(CacheControl.noStore())
                .body(new Items(categories.listPublic()));
    }

    record Items(List<CategoryService.CategoryView> items) {
    }

    static SessionService.Identity manager(CurrentAccount current, HttpServletRequest request) {
        var identity = current.require(request);
        if (!"manager".equals(identity.account().role())) {
            throw new BusinessError("ACTION_NOT_ALLOWED", 403, "需要平台管理权限");
        }
        return identity;
    }
}
