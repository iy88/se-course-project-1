package io.github.iy88.project1.api.category;

import io.github.iy88.project1.api.account.CurrentAccount;
import io.github.iy88.project1.category.application.CategoryService;
import io.github.iy88.project1.core.BusinessError;
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
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/admin/categories")
@Profile("infrastructure")
class AdminCategoryController {
    private final CategoryService categories;
    private final CurrentAccount current;

    AdminCategoryController(CategoryService categories, CurrentAccount current) {
        this.categories = categories;
        this.current = current;
    }

    @GetMapping
    ResponseEntity<Items> list(HttpServletRequest request) {
        CategoryController.manager(current, request);
        return ResponseEntity.ok().cacheControl(CacheControl.noStore())
                .body(new Items(categories.listAdmin()));
    }

    @PostMapping
    ResponseEntity<CategoryService.CategoryDetail> create(@RequestBody NameRequest body, HttpServletRequest request) {
        var manager = CategoryController.manager(current, request);
        return ResponseEntity.status(201).cacheControl(CacheControl.noStore())
                .body(categories.create(manager.account().id(), body.name()));
    }

    @PatchMapping("/{categoryId}")
    ResponseEntity<CategoryService.CategoryDetail> rename(@PathVariable String categoryId,
                                                          @RequestBody MainNameRequest body,
                                                          HttpServletRequest request) {
        CategoryController.manager(current, request);
        return ResponseEntity.ok().cacheControl(CacheControl.noStore())
                .body(categories.rename(id(categoryId), body.mainName()));
    }

    @PostMapping("/{categoryId}/aliases")
    ResponseEntity<CategoryService.AliasCreated> alias(@PathVariable String categoryId,
                                                       @RequestBody NameRequest body,
                                                       HttpServletRequest request) {
        CategoryController.manager(current, request);
        return ResponseEntity.status(201).cacheControl(CacheControl.noStore())
                .body(categories.addAlias(id(categoryId), body.name()));
    }

    @DeleteMapping("/{categoryId}/aliases/{categoryNameId}")
    ResponseEntity<Void> removeAlias(@PathVariable String categoryId, @PathVariable String categoryNameId,
                                     HttpServletRequest request) {
        CategoryController.manager(current, request);
        categories.removeAlias(id(categoryId), id(categoryNameId));
        return ResponseEntity.noContent().cacheControl(CacheControl.noStore()).build();
    }

    @PostMapping("/{categoryId}/disable")
    ResponseEntity<CategoryService.CategoryDetail> disable(@PathVariable String categoryId,
                                                           HttpServletRequest request) {
        CategoryController.manager(current, request);
        return ResponseEntity.ok().cacheControl(CacheControl.noStore())
                .body(categories.disable(id(categoryId)));
    }

    @DeleteMapping("/{categoryId}")
    ResponseEntity<Void> delete(@PathVariable String categoryId, HttpServletRequest request) {
        CategoryController.manager(current, request);
        categories.delete(id(categoryId));
        return ResponseEntity.noContent().cacheControl(CacheControl.noStore()).build();
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
        throw new BusinessError("INPUT_INVALID", 422, "标识无效");
    }

    record Items(List<CategoryService.CategoryDetail> items) {
    }

    record NameRequest(String name) {
    }

    record MainNameRequest(String mainName) {
    }
}
