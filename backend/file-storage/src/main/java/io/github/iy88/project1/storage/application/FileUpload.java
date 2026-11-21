package io.github.iy88.project1.storage.application;

import io.github.iy88.project1.storage.FilePurpose;
import io.github.iy88.project1.storage.OssFileObjects.Location;
import io.github.iy88.project1.storage.persistence.FileRulesProperties;
import io.github.iy88.project1.storage.persistence.UploadRegistration;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Service;

@Service
@Profile("infrastructure")
public class FileUpload {
    private final FileRulesProperties rules;

    public FileUpload(FileRulesProperties rules) {
        this.rules = rules;
    }

    public UploadRegistration.Draft prepare(long accountId, FilePurpose purpose, UploadRegistration.Target target,
                                            Location location, long declaredSize, String declaredType,
                                            String signingCredentialRef) {
        var now = Instant.now().truncatedTo(ChronoUnit.SECONDS);
        var draft = new UploadRegistration.Draft(accountId, purpose, target, location, declaredSize, declaredType,
                signingCredentialRef, now, now.plusSeconds(rules.uploadTtlSeconds()),
                now.plusSeconds(rules.tempRetentionSeconds()));
        draft.withRules(rules.rulesFor(purpose));
        return draft;
    }
}
