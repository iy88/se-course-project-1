package io.github.iy88.project1.api.cases;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import io.github.iy88.project1.core.BusinessError;
import java.util.List;
import org.junit.jupiter.api.Test;

/** Wire mapping for the explicit appeal selection fields. */
class CaseIdsTests {
    @Test
    void mapsTheSelectedOriginalAndReplacementEnforcements() {
        var request = new CaseRequests.Message(new CaseRequests.ThreadRef("case", "71"), "manager_reply",
                "adjust", null, "102", "adjust", "basis", " enf-1 ",
                List.of(new CaseRequests.Enforcement("adjust_trade_status", "trade", "900", "terminated")));

        var command = CaseIds.message(request);

        assertThat(command.originalEnforcementId()).isEqualTo("enf-1");
        assertThat(command.replacementEnforcements()).singleElement().satisfies(item -> {
            assertThat(item.action()).isEqualTo("adjust_trade_status");
            assertThat(item.targetType()).isEqualTo("trade");
            assertThat(item.targetId()).isEqualTo(900L);
            assertThat(item.expectedResult()).isEqualTo("terminated");
        });
    }

    @Test
    void treatsABlankOriginalAsAbsentAndRejectsOverlongIds() {
        var blank = new CaseRequests.Message(new CaseRequests.ThreadRef("case", "71"), "manager_reply",
                "uphold", null, "102", "uphold", "basis", "   ", List.of());
        assertThat(CaseIds.message(blank).originalEnforcementId()).isNull();

        var tooLong = new CaseRequests.Message(new CaseRequests.ThreadRef("case", "71"), "manager_reply",
                "revoke", null, "102", "revoke", "basis", "x".repeat(129), List.of());
        assertThatThrownBy(() -> CaseIds.message(tooLong))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("INPUT_INVALID"));
    }
}
