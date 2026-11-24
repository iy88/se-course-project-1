package io.github.iy88.project1.casemanagement.persistence;

import org.springframework.data.repository.Repository;

interface ModerationCaseActionRepository extends Repository<ModerationCaseAction, Long> {
    ModerationCaseAction save(ModerationCaseAction entity);
}
