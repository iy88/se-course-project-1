package io.github.iy88.project1.maintenance;

import java.util.ArrayList;
import java.util.List;

/** IDs and mode-specific pools produced by one seed transaction. */
final class SeedOutcome {
    long managerId;
    String managerEmail;
    final List<AccountRef> accounts = new ArrayList<>();
    final List<Long> productIds = new ArrayList<>();
    final List<Long> browseProductIds = new ArrayList<>();
    final List<TradePair> tradePairs = new ArrayList<>();
    final List<Long> categoryIds = new ArrayList<>();
    final List<Long> conversationIds = new ArrayList<>();
    final List<String> searchTerms = new ArrayList<>();
    final List<SeedFiles.UploadedFile> uploadedFiles = new ArrayList<>();
    final List<ScenarioRef> scenarios = new ArrayList<>();

    record AccountRef(long id, String alias, String email, String displayName, String role) {
    }

    record TradePair(long user, long peer, long productId, int productVersion) {
    }

    record ScenarioRef(String key, String kind, long id) {
    }
}
