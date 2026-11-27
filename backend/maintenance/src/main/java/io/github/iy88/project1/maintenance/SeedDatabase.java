package io.github.iy88.project1.maintenance;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Types;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

/** Small JDBC facade: explicit SQL, one transaction, no implicit retries or credential logging. */
final class SeedDatabase {
    private final Connection connection;

    SeedDatabase(Connection connection) {
        this.connection = connection;
    }

    Connection connection() {
        return connection;
    }

    void begin() throws SQLException {
        connection.setAutoCommit(false);
    }

    void commit() throws SQLException {
        connection.commit();
    }

    void rollback() {
        try {
            connection.rollback();
        } catch (SQLException ignored) {
            // The original failure is more useful than a rollback failure here.
        }
    }

    long insert(String sql, Object... parameters) throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement(sql)) {
            bind(statement, parameters);
            try (ResultSet rows = statement.executeQuery()) {
                if (!rows.next()) {
                    throw new IllegalStateException("Seed insert did not return a generated key");
                }
                return rows.getLong(1);
            }
        }
    }

    void update(String sql, Object... parameters) throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement(sql)) {
            bind(statement, parameters);
            statement.executeUpdate();
        }
    }

    long queryLong(String sql, Object... parameters) throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement(sql)) {
            bind(statement, parameters);
            try (ResultSet rows = statement.executeQuery()) {
                return rows.next() ? rows.getLong(1) : 0;
            }
        }
    }

    String queryString(String sql, Object... parameters) throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement(sql)) {
            bind(statement, parameters);
            try (ResultSet rows = statement.executeQuery()) {
                return rows.next() ? rows.getString(1) : null;
            }
        }
    }

    List<Long> queryLongs(String sql, Object... parameters) throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement(sql)) {
            bind(statement, parameters);
            try (ResultSet rows = statement.executeQuery()) {
                List<Long> result = new ArrayList<>();
                while (rows.next()) {
                    result.add(rows.getLong(1));
                }
                return result;
            }
        }
    }

    private static void bind(PreparedStatement statement, Object... parameters) throws SQLException {
        for (int index = 0; index < parameters.length; index++) {
            Object value = parameters[index];
            int position = index + 1;
            if (value == null) {
                statement.setNull(position, Types.NULL);
            } else if (value instanceof Instant instant) {
                statement.setObject(position, OffsetDateTime.ofInstant(instant, ZoneOffset.UTC));
            } else if (value instanceof UUID uuid) {
                statement.setObject(position, uuid);
            } else if (value instanceof Integer integer) {
                statement.setInt(position, integer);
            } else if (value instanceof Long number) {
                statement.setLong(position, number);
            } else if (value instanceof Boolean bool) {
                statement.setBoolean(position, bool);
            } else if (value instanceof byte[] bytes) {
                statement.setBytes(position, bytes);
            } else {
                statement.setString(position, value.toString());
            }
        }
    }
}
