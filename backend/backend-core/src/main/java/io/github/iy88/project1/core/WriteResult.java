package io.github.iy88.project1.core;

import java.util.UUID;

public record WriteResult<T>(UUID operationId, int status, T data, ResourceRef resource, boolean replayed) {
    public record Response<T>(int status, T data, ResourceRef resource) {
        public Response {
            if (status < 200 || status >= 300) {
                throw new IllegalArgumentException("Expected a successful operation status");
            }
            if (status == 204 && data != null) {
                throw new IllegalArgumentException("HTTP 204 has no response body");
            }
        }
    }
}
