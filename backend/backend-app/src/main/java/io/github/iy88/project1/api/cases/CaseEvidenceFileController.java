package io.github.iy88.project1.api.cases;

import io.github.iy88.project1.casemanagement.CaseVocabulary;
import io.github.iy88.project1.casemanagement.application.CasePorts;
import io.github.iy88.project1.casemanagement.application.CaseRecords;
import io.github.iy88.project1.casemanagement.persistence.CaseLifecycleStore;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.storage.OssClients;
import io.github.iy88.project1.storage.OssFileObjects;
import io.github.iy88.project1.storage.application.FileRead;
import io.github.iy88.project1.storage.persistence.FileRegistry;
import io.github.iy88.project1.storage.persistence.UploadRegistration;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.boot.autoconfigure.condition.ConditionalOnWebApplication;
import org.springframework.context.annotation.Profile;
import org.springframework.core.env.Environment;
import org.springframework.http.CacheControl;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Authorized read of one verified attachment. The route is deliberately case-only and
 * signs in the request after rechecking the current session, manager role, claim and
 * case/file pairing inside the file read transaction.
 */
@RestController
@RequestMapping("/api/v1")
@Profile("!dependency-probe & !file-probe")
@ConditionalOnWebApplication(type = ConditionalOnWebApplication.Type.SERVLET)
public class CaseEvidenceFileController {
    private static final String REFERRER_POLICY = "Referrer-Policy";

    private final CaseHttpSupport support;
    private final ObjectProvider<CaseLifecycleStore> store;
    private final ObjectProvider<CasePorts.Managers> managers;
    private final ObjectProvider<FileRead> reads;
    private final Environment environment;

    CaseEvidenceFileController(CaseHttpSupport support, ObjectProvider<CaseLifecycleStore> store,
                               ObjectProvider<CasePorts.Managers> managers, ObjectProvider<FileRead> reads,
                               Environment environment) {
        this.support = support;
        this.store = store;
        this.managers = managers;
        this.reads = reads;
        this.environment = environment;
    }

    @GetMapping("/admin/cases/{case_id}/evidence/{evidence_id}/file")
    ResponseEntity<Void> file(HttpServletRequest request,
                              @PathVariable("case_id") String caseId,
                              @PathVariable("evidence_id") String evidenceId) {
        return file(request, caseId, evidenceId, false);
    }

    @GetMapping("/cases/{case_id}/evidence/{evidence_id}/file")
    ResponseEntity<Void> reporterFile(HttpServletRequest request,
                                      @PathVariable("case_id") String caseId,
                                      @PathVariable("evidence_id") String evidenceId) {
        return file(request, caseId, evidenceId, true);
    }

    private ResponseEntity<Void> file(HttpServletRequest request, String caseId, String evidenceId,
                                      boolean reporterView) {
        long caseKey = CaseIds.path(caseId);
        long evidenceKey = CaseIds.path(evidenceId);
        var context = support.context(request);
        var lifecycle = store.getIfAvailable();
        var managerPort = managers.getIfAvailable();
        var fileReads = reads.getIfAvailable();
        if (lifecycle == null || managerPort == null || fileReads == null) {
            throw CaseHttpSupport.unavailable();
        }
        long fileId = requireCurrentAccess(lifecycle, managerPort, context, caseKey, evidenceKey,
                null, reporterView);
        var target = new UploadRegistration.Target("case", caseKey);
        var settings = settings();
        try {
            var authorized = OssClients.use(settings.endpoint(), settings.region(),
                    settings.accessKeyId(), settings.accessKeySecret(), client -> fileReads.prepare(target, fileId,
                            new OssFileObjects(client, settings.bucket(), settings.prefix()),
                            () -> requireCurrentAccess(lifecycle, managerPort, context, caseKey, evidenceKey,
                                    fileId, reporterView)));
            return ResponseEntity.status(HttpStatus.FOUND).location(authorized.url())
                    .cacheControl(CacheControl.noStore())
                    .header(REFERRER_POLICY, "no-referrer")
                    .build();
        } catch (FileRegistry.Rejected rejected) {
            throw notVisible();
        } catch (OssFileObjects.Failure failure) {
            if (failure.reason() == OssFileObjects.Reason.INVALID_CONFIGURATION) {
                throw new BusinessError("STORAGE_CONFIGURATION_INVALID", 503, "存储配置无效");
            }
            throw storageUnavailable();
        } catch (IllegalStateException | IllegalArgumentException failure) {
            throw storageUnavailable();
        }
    }

    /** Runs inside {@link FileRead#prepare} before the active reference is read. */
    private static long requireCurrentAccess(CaseLifecycleStore store, CasePorts.Managers managers,
                                             ExecutionContext context, long caseId, long evidenceId, Long fileId,
                                             boolean reporterView) {
        long actor = actor(context);
        if (reporterView) {
            store.find(caseId).filter(facts -> CaseVocabulary.REPORT.equals(facts.caseType()) && facts.reportedBy(actor))
                    .orElseThrow(CaseEvidenceFileController::notVisible);
        } else {
            requireClaim(store, managers, context, caseId, actor);
        }
        var evidence = requireEvidence(store, caseId, evidenceId, fileId);
        if (reporterView && !evidence.submittedAttachmentBy(actor)) {
            throw notVisible();
        }
        return evidence.fileId();
    }

    private static CaseRecords.Facts requireClaim(CaseLifecycleStore store, CasePorts.Managers managers,
                                                  ExecutionContext context, long caseId, long actor) {
        var facts = store.find(caseId).filter(CaseRecords.Facts::lifecycle).orElseThrow(
                CaseEvidenceFileController::notVisible);
        if (!facts.claimedBy(actor)) {
            throw notVisible();
        }
        try {
            managers.requireManager(context);
        } catch (BusinessError denied) {
            if (denied.status() == 403) {
                throw notVisible();
            }
            throw denied;
        }
        return facts;
    }

    private static CaseRecords.Evidence requireEvidence(CaseLifecycleStore store, long caseId, long evidenceId,
                                                        Long expectedFileId) {
        var evidence = store.evidence(caseId, evidenceId).orElseThrow(CaseEvidenceFileController::notVisible);
        if (evidence.fileId() == null
                || (expectedFileId != null && !expectedFileId.equals(evidence.fileId()))) {
            throw notVisible();
        }
        return evidence;
    }

    private static long actor(ExecutionContext context) {
        if (context.actorKind() != ExecutionContext.ActorKind.ACCOUNT) {
            throw notVisible();
        }
        try {
            long actor = Long.parseLong(context.actorId());
            if (actor > 0) {
                return actor;
            }
        } catch (NumberFormatException ignored) {
            // Fall through to the hidden case error.
        }
        throw notVisible();
    }

    private OssSettings settings() {
        try {
            return new OssSettings(environment.getRequiredProperty("OSS_ENDPOINT"),
                    environment.getRequiredProperty("OSS_REGION"),
                    environment.getRequiredProperty("OSS_BUCKET"),
                    environment.getRequiredProperty("OSS_PREFIX"),
                    environment.getRequiredProperty("OSS_ACCESS_KEY_ID"),
                    environment.getRequiredProperty("OSS_ACCESS_KEY_SECRET"));
        } catch (RuntimeException missing) {
            throw storageUnavailable();
        }
    }

    private static BusinessError storageUnavailable() {
        return new BusinessError("STORAGE_UNAVAILABLE", 503, "存储暂不可用");
    }

    private static BusinessError notVisible() {
        return new BusinessError("RESOURCE_NOT_VISIBLE", 404, "事项不可见");
    }

    private record OssSettings(String endpoint, String region, String bucket, String prefix,
                               String accessKeyId, String accessKeySecret) {
    }
}
