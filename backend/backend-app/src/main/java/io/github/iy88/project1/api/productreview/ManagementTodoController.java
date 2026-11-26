package io.github.iy88.project1.api.productreview;

import io.github.iy88.project1.api.PageSettings;
import io.github.iy88.project1.core.BusinessError;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.http.CacheControl;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import tools.jackson.databind.JsonNode;

@RestController
@RequestMapping("/api/v1/management")
class ManagementTodoController {
    private final ReviewHttpSupport support;
    private final PageSettings pages;

    ManagementTodoController(ReviewHttpSupport support, PageSettings pages) {
        this.support = support;
        this.pages = pages;
    }

    @GetMapping("/todos")
    ResponseEntity<JsonNode> todos(@RequestParam(value = "page", required = false) Integer page,
                   @RequestParam(value = "page_size", required = false) Integer pageSize,
                   @RequestParam(value = "ownership", required = false) String ownership,
                   @RequestParam(value = "kind", required = false) String kind,
                   HttpServletRequest request) {
        var context = support.context(request);
        int resolvedPage = page == null ? 1 : page;
        int resolvedSize = pageSize == null ? pages.pageSizeDefault() : pageSize;
        if (resolvedPage <= 0 || resolvedSize <= 0 || resolvedSize > pages.pageSizeMax()) {
            throw new BusinessError("INPUT_INVALID", 422, "分页参数无效");
        }
        return ResponseEntity.ok().cacheControl(CacheControl.noStore())
                .body(support.reviews().todos(context, ownership, kind, resolvedPage, resolvedSize));
    }
}
