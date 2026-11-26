package io.github.iy88.project1.api;

import com.fasterxml.jackson.annotation.JsonInclude;
import io.github.iy88.project1.core.BusinessError;
import jakarta.servlet.http.HttpServletRequest;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import java.util.Map;
import java.util.UUID;
import org.springframework.dao.DataAccessException;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.dao.TransientDataAccessException;

import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.transaction.CannotCreateTransactionException;
import org.springframework.transaction.TransactionException;
import org.springframework.transaction.TransactionTimedOutException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.ServletRequestBindingException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.HandlerMethodValidationException;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;

@RestControllerAdvice(basePackages = "io.github.iy88.project1.api")
public class ApiErrors {
    private static final Logger LOG = LoggerFactory.getLogger(ApiErrors.class);

    @ExceptionHandler(BusinessError.class)
    public ResponseEntity<Envelope> business(BusinessError failure, HttpServletRequest request) {
        ResponseEntity.BodyBuilder response = ResponseEntity.status(failure.status());
        if ("RATE_LIMITED".equals(failure.code())) {
            Object retryAfter = failure.details().get("retry_after_seconds");
            if (retryAfter != null) {
                response.header(HttpHeaders.RETRY_AFTER, retryAfter.toString());
            }
        }
        return response.body(new Envelope(new Error(failure.code(), failure.getMessage(), failure.details()),
                ApiRequestContext.requestId(request), failure.operationId()));
    }

    @ExceptionHandler({HttpMessageNotReadableException.class, MethodArgumentTypeMismatchException.class,
            MethodArgumentNotValidException.class, ServletRequestBindingException.class})
    public ResponseEntity<Envelope> invalidInput(HttpServletRequest request) {
        return business(new BusinessError("INPUT_INVALID", 422, "请求参数无效"), request);
    }

    @ExceptionHandler(HandlerMethodValidationException.class)
    public ResponseEntity<Envelope> validation(HandlerMethodValidationException failure, HttpServletRequest request) {
        return failure.isForReturnValue() ? internalFailure(failure, request) : invalidInput(request);
    }

    @ExceptionHandler({TransientDataAccessException.class, DataAccessResourceFailureException.class,
            CannotCreateTransactionException.class, TransactionTimedOutException.class})
    public ResponseEntity<Envelope> databaseUnavailable(HttpServletRequest request) {
        return business(new BusinessError("DEPENDENCY_UNAVAILABLE", 503, "服务暂不可用"), request);
    }

    @ExceptionHandler({DataAccessException.class, TransactionException.class})
    public ResponseEntity<Envelope> internalFailure(RuntimeException failure, HttpServletRequest request) {
        LOG.error("api request_id={} failure={}",
                ApiRequestContext.requestId(request), failure.getClass().getSimpleName());
        return business(new BusinessError("INTERNAL_ERROR", 500, "请求处理失败"), request);
    }

    private static ResponseEntity<Envelope> respond(int status, Envelope body) {
        return ResponseEntity.status(status).body(body);
    }

    public record Error(String code, String message, Map<String, ?> details) {}
    public record Envelope(Error error, UUID request_id,
                           @JsonInclude(JsonInclude.Include.NON_NULL) UUID operation_id) {}
}
