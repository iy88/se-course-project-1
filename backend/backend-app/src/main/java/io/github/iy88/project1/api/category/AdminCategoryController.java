package io.github.iy88.project1.api.category;

import io.github.iy88.project1.api.ApiRequestContext;
import io.github.iy88.project1.api.PageSettings;
import io.github.iy88.project1.api.account.CurrentAccount;
import io.github.iy88.project1.category.application.CategoryService;
import io.github.iy88.project1.core.AuditContext;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import jakarta.servlet.http.HttpServletRequest;
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
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/admin/categories")
@Profile("infrastructure")
class AdminCategoryController {
    private final CategoryService categories;
    private final CurrentAccount current;
    private final ApiRequestContext requestContext;
    private final PageSettings pages;

    AdminCategoryController(CategoryService categories, CurrentAccount current, ApiRequestContext requestContext,
                            PageSettings pages) {
        this.categories = categories;
        this.current = current;
        this.requestContext = requestContext;
        this.pages = pages;
    }

    @GetMapping
    ResponseEntity<CategoryService.CategoryPage> list(
            @RequestParam(value = "page", required = false) Integer page,
            @RequestParam(value = "page_size", required = false) Integer pageSize,
            HttpServletRequest request) {
        CategoryController.manager(current, request);
        int resolvedPage = page == null ? 1 : page;
        int resolvedSize = pageSize == null ? pages.pageSizeDefault() : pageSize;
        if (resolvedPage <= 0 || resolvedSize <= 0 || resolvedSize > pages.pageSizeMax()) {
            throw new BusinessError("INPUT_INVALID", 422, "分页参数无效");
        }
        return ResponseEntity.ok().cacheControl(CacheControl.noStore())
                .body(categories.listAdmin(resolvedPage, resolvedSize));
    }

    @PostMapping
    ResponseEntity<CategoryService.CategoryDetail> create(@RequestBody NameRequest body, HttpServletRequest request) {
        var manager = CategoryController.manager(current, request);
        return ResponseEntity.status(201).cacheControl(CacheControl.noStore())
                .body(categories.create(manager.account().id(), body.name(), writeContext(manager, request)));
    }

    @PatchMapping("/{categoryId}")
    ResponseEntity<CategoryService.CategoryDetail> rename(@PathVariable String categoryId,
                                                          @RequestBody MainNameRequest body,
                                                          HttpServletRequest request) {
        var manager = CategoryController.manager(current, request);
        return ResponseEntity.ok().cacheControl(CacheControl.noStore())
                .body(categories.rename(id(categoryId), body.mainName(), writeContext(manager, request)));
    }

    @PostMapping("/{categoryId}/aliases")
    ResponseEntity<CategoryService.AliasCreated> alias(@PathVariable String categoryId,
                                                       @RequestBody NameRequest body,
                                                       HttpServletRequest request) {
        var manager = CategoryController.manager(current, request);
        return ResponseEntity.status(201).cacheControl(CacheControl.noStore())
                .body(categories.addAlias(id(categoryId), body.name(), writeContext(manager, request)));
    }

    @DeleteMapping("/{categoryId}/aliases/{categoryNameId}")
    ResponseEntity<Void> removeAlias(@PathVariable String categoryId, @PathVariable String categoryNameId,
                                     HttpServletRequest request) {
        var manager = CategoryController.manager(current, request);
        categories.removeAlias(id(categoryId), id(categoryNameId), writeContext(manager, request));
        return ResponseEntity.noContent().cacheControl(CacheControl.noStore()).build();
    }

    @PostMapping("/{categoryId}/disable")
    ResponseEntity<CategoryService.CategoryDetail> disable(@PathVariable String categoryId,
                                                           HttpServletRequest request) {
        var manager = CategoryController.manager(current, request);
        return ResponseEntity.ok().cacheControl(CacheControl.noStore())
                .body(categories.disable(id(categoryId), writeContext(manager, request)));
    }

    @DeleteMapping("/{categoryId}")
    ResponseEntity<Void> delete(@PathVariable String categoryId, HttpServletRequest request) {
        var manager = CategoryController.manager(current, request);
        categories.delete(id(categoryId), writeContext(manager, request));
        return ResponseEntity.noContent().cacheControl(CacheControl.noStore()).build();
    }

    private AuditContext writeContext(
            io.github.iy88.project1.account.application.SessionService.Identity manager,
            HttpServletRequest request) {
        return requestContext.forWrite(request, ExecutionContext.ActorKind.ACCOUNT,
                Long.toString(manager.account().id()), manager.guard().id(), null,
                (long) manager.guard().credentialVersion());
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

    record NameRequest(String name) {
    }

    record MainNameRequest(String mainName) {
    }
}
