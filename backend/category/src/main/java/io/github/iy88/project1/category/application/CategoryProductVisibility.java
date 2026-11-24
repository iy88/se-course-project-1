package io.github.iy88.project1.category.application;

/** Read-only product facts needed by category views; implemented by the product module. */
public interface CategoryProductVisibility {
    boolean hasPublicProducts(long categoryId);

    long associatedProductCount(long categoryId);
}
