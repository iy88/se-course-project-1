package io.github.iy88.project1.product.application;

import io.github.iy88.project1.category.application.CategoryProductVisibility;
import io.github.iy88.project1.product.persistence.ProductCategoryRepository;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Service;

@Service
@Profile("infrastructure")
public class ProductCategoryVisibility implements CategoryProductVisibility {
    private final ProductCategoryRepository links;

    public ProductCategoryVisibility(ProductCategoryRepository links) {
        this.links = links;
    }

    @Override
    public boolean hasPublicProducts(long categoryId) {
        return links.existsPublicProductInCategory(categoryId);
    }

    @Override
    public long associatedProductCount(long categoryId) {
        return links.countProductsInCategory(categoryId);
    }
}
