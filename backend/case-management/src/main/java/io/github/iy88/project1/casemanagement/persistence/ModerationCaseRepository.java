package io.github.iy88.project1.casemanagement.persistence;

import java.util.Optional;
import org.springframework.data.repository.Repository;

interface ModerationCaseRepository extends Repository<ModerationCase, Long> {
    ModerationCase save(ModerationCase entity);

    Optional<ModerationCase> findById(long id);
}
