package io.github.iy88.project1.account.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.mockStatic;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.aliyun.sdk.service.oss2.OSSClient;
import io.github.iy88.project1.storage.OssClients;
import io.github.iy88.project1.storage.OssFileObjects;
import io.github.iy88.project1.storage.application.FileRead;
import io.github.iy88.project1.storage.persistence.FileReferences;
import io.github.iy88.project1.storage.persistence.UploadRegistration;
import java.net.URI;
import java.time.Instant;
import java.util.List;
import java.util.function.Function;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.mockito.MockedStatic;
import org.springframework.core.env.Environment;
import org.springframework.transaction.support.TransactionSynchronizationManager;

class AccountAvatarServiceTests {
    private final FileReferences references = mock(FileReferences.class);
    private final FileRead reads = mock(FileRead.class);
    private final Environment environment = mock(Environment.class);
    private final AccountAvatarService service = avatarService();

    @AfterEach
    void clearTransaction() {
        TransactionSynchronizationManager.setActualTransactionActive(false);
    }

    @Test
    void signsAvatarInsideAnExistingWriteTransactionWithoutStartingANestedTransaction() {
        var target = new UploadRegistration.Target("account", 7L);
        when(references.current(target, "avatar"))
                .thenReturn(List.of(new FileReferences.Reference(9L, 11L, target, "avatar", "7",
                        Instant.parse("2026-11-26T00:00:00Z"))));
        var read = new FileRead.AuthorizedRead(11L, URI.create("https://example.test/avatar"),
                Instant.parse("2026-11-26T00:05:00Z"), "image/png", 42L);
        when(reads.signInReadSnapshot(eq(target), eq(11L), any(OssFileObjects.class))).thenReturn(read);
        TransactionSynchronizationManager.setActualTransactionActive(true);

        try (MockedStatic<OssClients> clients = mockStatic(OssClients.class)) {
            clients.when(() -> OssClients.use(anyString(), anyString(), anyString(), anyString(), any()))
                    .thenAnswer(invocation -> {
                        Function<OSSClient, Object> action = invocation.getArgument(4);
                        return action.apply(mock(OSSClient.class));
                    });

            assertThat(service.currentUrl(7L)).isEqualTo("https://example.test/avatar");
        }

        verify(reads).signInReadSnapshot(eq(target), eq(11L), any(OssFileObjects.class));
    }

    private AccountAvatarService avatarService() {
        when(environment.getRequiredProperty("OSS_ENDPOINT")).thenReturn("https://oss.example.test");
        when(environment.getRequiredProperty("OSS_REGION")).thenReturn("test-region");
        when(environment.getRequiredProperty("OSS_BUCKET")).thenReturn("test-bucket");
        when(environment.getRequiredProperty("OSS_PREFIX")).thenReturn("test-prefix");
        when(environment.getRequiredProperty("OSS_ACCESS_KEY_ID")).thenReturn("test-id");
        when(environment.getRequiredProperty("OSS_ACCESS_KEY_SECRET")).thenReturn("test-secret");
        return new AccountAvatarService(references, reads, environment);
    }
}
