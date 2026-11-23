package io.github.iy88.project1.trade.persistence;

import org.springframework.data.repository.Repository;

interface AgreementDecisionRows extends Repository<AgreementDecisionRow, Long> {
    AgreementDecisionRow save(AgreementDecisionRow row);
}
