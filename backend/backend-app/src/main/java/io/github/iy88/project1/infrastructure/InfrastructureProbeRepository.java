package io.github.iy88.project1.infrastructure;

import java.util.Optional;
import org.springframework.data.repository.Repository;

interface InfrastructureProbeRepository extends Repository<InfrastructureProbeEntry, Integer> {

    Optional<InfrastructureProbeEntry> findById(Integer id);
}
