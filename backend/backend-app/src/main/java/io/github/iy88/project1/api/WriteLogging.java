package io.github.iy88.project1.api;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.WriteResult;
import java.util.concurrent.TimeUnit;
import org.aspectj.lang.ProceedingJoinPoint;
import org.aspectj.lang.annotation.Around;
import org.aspectj.lang.annotation.Aspect;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

@Aspect
@Component
public class WriteLogging {
    private static final org.slf4j.Logger LOG = LoggerFactory.getLogger(WriteLogging.class);

    @Around(value = "execution(* io.github.iy88.project1.core.WriteExecutor.run(..)) && args(context, operation, ..)",
            argNames = "call,context,operation")
    public Object record(ProceedingJoinPoint call, ExecutionContext context, String operation) throws Throwable {
        long start = System.nanoTime();
        try {
            var result = (WriteResult<?>) call.proceed();
            LOG.info("write request_id={} operation_id={} action={} result={} elapsed_ms={}", context.requestId(),
                    result.operationId(), operation, result.replayed() ? "replayed" : "committed", elapsed(start));
            return result;
        } catch (BusinessError rejection) {
            LOG.info("write request_id={} operation_id={} action={} result={} elapsed_ms={}", context.requestId(),
                    rejection.operationId(), operation, rejection.code(), elapsed(start));
            throw rejection;
        } catch (Throwable failure) {
            LOG.error("write request_id={} action={} result={} elapsed_ms={}", context.requestId(),
                    operation, failure.getClass().getSimpleName(), elapsed(start), failure);
            throw failure;
        }
    }

    private static long elapsed(long start) {
        return TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - start);
    }
}
