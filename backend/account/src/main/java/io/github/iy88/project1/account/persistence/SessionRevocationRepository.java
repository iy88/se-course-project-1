package io.github.iy88.project1.account.persistence;

import java.util.UUID;
import org.springframework.data.repository.Repository;

public interface SessionRevocationRepository extends Repository<SessionRevocation, UUID> {
    SessionRevocation save(SessionRevocation revocation);
}
