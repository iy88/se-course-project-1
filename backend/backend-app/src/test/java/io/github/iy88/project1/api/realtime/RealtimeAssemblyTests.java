package io.github.iy88.project1.api.realtime;

import io.github.iy88.project1.messaging.RealtimeEventSources;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.boot.autoconfigure.condition.ConditionalOnWebApplication;
import org.springframework.context.annotation.Profile;
import org.springframework.core.annotation.AnnotatedElementUtils;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;

class RealtimeAssemblyTests {
    private static final String SERVLET_ROLE = "infrastructure & !dependency-probe & !file-probe";

    private final RealtimeSessions sessions = mock(RealtimeSessions.class);
    private final RealtimeEventSources.Notifications notifications =
            mock(RealtimeEventSources.Notifications.class);
    private final RealtimeEventSources.Conversations conversations =
            mock(RealtimeEventSources.Conversations.class);

    @Test
    void normalInfrastructureServletEntryAssemblesWebSocketRecoveryCapabilitiesAndProjection() {
        for (var type : List.of(RealtimeConfiguration.class, EventRecoveryController.class,
                CapabilitiesController.class, BusinessRealtimeConfiguration.class)) {
            var profile = AnnotatedElementUtils.findMergedAnnotation(type, Profile.class);
            assertThat(profile).as(type.getSimpleName()).isNotNull();
            assertThat(profile.value()).as(type.getSimpleName()).containsExactly(SERVLET_ROLE);

            var web = AnnotatedElementUtils.findMergedAnnotation(type, ConditionalOnWebApplication.class);
            assertThat(web).as(type.getSimpleName()).isNotNull();
            assertThat(web.type()).as(type.getSimpleName())
                    .isEqualTo(ConditionalOnWebApplication.Type.SERVLET);
        }
    }

    @Test
    void businessProjectionRequiresTheSessionAndBothBusinessReadAdapters() {
        var configuration = new BusinessRealtimeConfiguration();

        assertThat(configuration.realtimeAccess(sessions, notifications, conversations, List.of()))
                .isInstanceOf(BusinessRealtimeAccess.class);
        assertThatThrownBy(() -> configuration.realtimeAccess(null, notifications, conversations, List.of()))
                .isInstanceOf(NullPointerException.class)
                .hasMessageContaining("RealtimeSessions");
        assertThatThrownBy(() -> configuration.realtimeAccess(sessions, null, conversations, List.of()))
                .isInstanceOf(NullPointerException.class)
                .hasMessageContaining("Notifications");
        assertThatThrownBy(() -> configuration.realtimeAccess(sessions, notifications, null, List.of()))
                .isInstanceOf(NullPointerException.class)
                .hasMessageContaining("Conversations");
    }
}
