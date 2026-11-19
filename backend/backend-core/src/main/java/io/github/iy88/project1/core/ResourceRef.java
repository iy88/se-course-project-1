package io.github.iy88.project1.core;

public record ResourceRef(String type, long id) {
    public ResourceRef {
        if (type == null || type.isBlank() || id <= 0) {
            throw new IllegalArgumentException("Invalid resource reference");
        }
    }
}
