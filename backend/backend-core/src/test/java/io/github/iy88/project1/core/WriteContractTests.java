package io.github.iy88.project1.core;

import java.util.List;
import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;

import static org.assertj.core.api.Assertions.assertThat;

class WriteContractTests {
    @Test
    void hashesNestedObjectsIndependentlyOfPropertyOrder() {
        var json = JsonMapper.builder().build();
        var first = json.readTree("""
                {"name":"item","options":{"y":1,"x":2},"files":[1,2]}
                """);
        var reordered = json.readTree("""
                {"files":[1,2],"options":{"x":2,"y":1},"name":"item"}
                """);
        var different = json.readTree("""
                {"files":[2,1],"options":{"x":2,"y":1},"name":"item"}
                """);

        assertThat(WriteExecutor.digest(first)).isEqualTo(WriteExecutor.digest(reordered));
        assertThat(WriteExecutor.digest(first)).isNotEqualTo(WriteExecutor.digest(different));
    }

    @Test
    void mergePreservesTheStrongestAccountModeAndOrdersResourceKeysNumerically() {
        var earlier = new LockPlan.Key(LockPlan.Domain.TRADE, List.of(2L));
        var later = new LockPlan.Key(LockPlan.Domain.TRADE, List.of(10L));
        var caseKey = new LockPlan.Key(LockPlan.Domain.CASE, List.of(1L));
        var original = new LockPlan(Map.of(1L, LockPlan.AccountMode.SHARED), Set.of(earlier, later));
        var additional = new LockPlan(Map.of(1L, LockPlan.AccountMode.EXCLUSIVE), Set.of(caseKey));

        var merged = original.merge(additional);

        assertThat(merged.accounts()).containsEntry(1L, LockPlan.AccountMode.EXCLUSIVE);
        assertThat(merged.resources().stream().sorted()).containsExactly(earlier, later, caseKey);
    }
}
