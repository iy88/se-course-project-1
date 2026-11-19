package io.github.iy88.project1.infrastructure;

import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

@Entity
@Table(name = "infrastructure_probe")
class InfrastructureProbeEntry {

    @Id
    private Integer id;

    protected InfrastructureProbeEntry() {
    }

    Integer getId() {
        return id;
    }
}
