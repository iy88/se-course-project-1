package io.github.iy88.project1.infrastructure;

import org.springframework.data.repository.Repository;

interface InfrastructureProbeRepository extends Repository<InfrastructureProbeEntry, Integer> {

    boolean existsById(Integer id);
}
