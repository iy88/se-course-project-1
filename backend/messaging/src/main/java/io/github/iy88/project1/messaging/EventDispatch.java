package io.github.iy88.project1.messaging;

import java.util.Map;
import java.util.UUID;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Profile;
import org.springframework.data.redis.connection.RedisStreamCommands.XAddOptions;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionTemplate;

@Service
@Profile("infrastructure")
public class EventDispatch {
    private static final Logger LOG = LoggerFactory.getLogger(EventDispatch.class);
    private final JdbcClient jdbc;
    private final TransactionTemplate transaction;
    private final DeliverySettings settings;
    private final StringRedisTemplate redis;
    private final String stream;

    public EventDispatch(JdbcClient jdbc, TransactionTemplate transaction, DeliverySettings settings,
                         StringRedisTemplate redis, @Value("${project1.redis.namespace}") String namespace) {
        this.jdbc = jdbc;
        this.transaction = transaction;
        this.settings = settings;
        this.redis = redis;
        this.stream = namespace + ":events";
    }

    @Transactional(propagation = Propagation.NEVER)
    public int publishDue() {
        int published = 0;
        for (int index = 0; index < settings.batchSize(); index++) {
            var token = UUID.randomUUID();
            var event = transaction.execute(status -> claim(token));
            if (event == null) break;

            try {
                var id = redis.opsForStream().add(stream, Map.of("event_id", event.id().toString(),
                        "recipient_account_id", Long.toString(event.account()), "account_seq", Long.toString(event.sequence())),
                        XAddOptions.maxlen(settings.streamMaxLength()));
                if (id == null) throw new IllegalStateException("Redis did not confirm the event");
            } catch (RuntimeException failure) {
                retry(event, token);
                continue;
            }

            published += jdbc.sql("""
                    UPDATE user_event SET published_at = statement_timestamp(), lease_token = NULL, lease_until = NULL
                    WHERE event_id = :id AND lease_token = :token AND lease_until > statement_timestamp()
                    """).param("id", event.id()).param("token", token).update();
        }
        return published;
    }

    private Claimed claim(UUID token) {
        return jdbc.sql("""
                WITH candidate AS (
                    SELECT event_id FROM user_event WHERE published_at IS NULL
                        AND next_attempt_at <= statement_timestamp() AND expires_at > statement_timestamp()
                        AND (lease_until IS NULL OR lease_until <= statement_timestamp())
                    ORDER BY next_attempt_at, event_id LIMIT 1 FOR UPDATE SKIP LOCKED
                )
                UPDATE user_event e SET lease_token = :token, attempts = e.attempts + 1,
                    lease_until = statement_timestamp() + :lease * interval '1 second'
                FROM candidate c WHERE e.event_id = c.event_id
                RETURNING e.event_id, e.recipient_account_id, e.account_seq, e.attempts
                """).param("token", token).param("lease", settings.leaseSeconds()).query((row, index) ->
                new Claimed(row.getObject(1, UUID.class), row.getLong(2), row.getLong(3), row.getInt(4)))
                .optional().orElse(null);
    }

    private void retry(Claimed event, UUID token) {
        boolean slow = event.attempts() >= settings.retryLimit();
        int delay = slow ? 300 : settings.retryDelay(event.attempts());
        int changed = jdbc.sql("""
                UPDATE user_event SET lease_token = NULL, lease_until = NULL,
                    next_attempt_at = statement_timestamp() + :delay * interval '1 second'
                WHERE event_id = :id AND lease_token = :token AND lease_until > statement_timestamp()
                """).param("delay", delay).param("id", event.id()).param("token", token).update();
        if (slow && changed != 0) LOG.warn("event_id={} result=publish_retry", event.id());
    }

    private record Claimed(UUID id, long account, long sequence, int attempts) {}
}
