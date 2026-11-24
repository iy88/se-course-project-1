package io.github.iy88.project1.category.application;

import io.github.iy88.project1.category.CategorySettings;
import io.github.iy88.project1.category.persistence.BannedItem;
import io.github.iy88.project1.category.persistence.BannedItemRepository;
import io.github.iy88.project1.category.persistence.BannedScopeState;
import io.github.iy88.project1.category.persistence.BannedScopeStateRepository;
import io.github.iy88.project1.core.BusinessError;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

@Service
@Profile("infrastructure")
public class BannedScopeService {
    private static final List<String> GROUPS = List.of("legal_prohibited", "dangerous_controlled", "live_animals",
            "medicine_device", "account_virtual", "service_promotion", "other");

    private final BannedItemRepository items;
    private final BannedScopeStateRepository states;
    private final CategorySettings settings;
    private final TransactionTemplate transaction;

    public BannedScopeService(BannedItemRepository items, BannedScopeStateRepository states,
                              CategorySettings settings, PlatformTransactionManager manager) {
        this.items = items;
        this.states = states;
        this.settings = settings;
        this.transaction = new TransactionTemplate(manager);
    }

    public BannedScopeView view() {
        List<BannedItem> current = items.findByDeletedAtIsNullOrderByDisplayOrderAscIdAsc();
        Instant updatedAt = current.stream().map(BannedItem::updatedAt).max(Instant::compareTo).orElse(null);
        List<GroupView> groups = new ArrayList<>();
        for (String group : GROUPS) {
            List<ItemView> grouped = current.stream().filter(item -> group.equals(item.group()))
                    .map(item -> new ItemView(Long.toString(item.id()), item.content(), item.displayOrder()))
                    .toList();
            if (!grouped.isEmpty()) {
                groups.add(new GroupView(group, grouped));
            }
        }
        return new BannedScopeView(updatedAt, groups);
    }

    public BannedScopeView replace(long adminId, List<Input> inputs) {
        if (inputs == null || inputs.isEmpty()) {
            throw new BusinessError("BANNED_SCOPE_INCOMPLETE", 422, "禁发范围不能为空");
        }
        List<Validated> validated = inputs.stream().map(this::validate).toList();
        transaction.executeWithoutResult(status -> {
            BannedScopeState state = states.lock()
                    .orElseThrow(() -> new IllegalStateException("Banned scope state row is missing"));
            Instant now = Instant.now();
            Set<Long> retained = new HashSet<>();
            for (Validated input : validated) {
                if (input.id != null) {
                    BannedItem item = items.findById(input.id)
                            .orElseThrow(() -> new BusinessError("INPUT_INVALID", 422, "禁发条目不存在"));
                    if (item.deleted()) {
                        throw new BusinessError("INPUT_INVALID", 422, "禁发条目不存在");
                    }
                    item.update(input.group, input.content, input.displayOrder, adminId, now);
                    items.save(item);
                    retained.add(input.id);
                } else {
                    BannedItem item = items.save(new BannedItem(input.group, input.content, input.displayOrder,
                            adminId, now));
                    retained.add(item.id());
                }
            }
            for (BannedItem existing : items.findByDeletedAtIsNullOrderByDisplayOrderAscIdAsc()) {
                if (!retained.contains(existing.id())) {
                    existing.delete(now);
                    items.save(existing);
                }
            }
            state.touch(now);
            states.save(state);
        });
        return view();
    }

    private Validated validate(Input input) {
        if (!GROUPS.contains(input.group())) {
            throw new BusinessError("INPUT_INVALID", 422, "禁发分组无效");
        }
        String content = input.content() == null ? "" : input.content().trim();
        if (content.isEmpty() || content.codePointCount(0, content.length()) > settings.bannedContentMaxLength()) {
            throw new BusinessError("INPUT_INVALID", 422, "禁发内容无效");
        }
        if (input.displayOrder() == null || input.displayOrder() < 0) {
            throw new BusinessError("INPUT_INVALID", 422, "展示顺序无效");
        }
        Long id = null;
        if (input.bannedItemId() != null && !input.bannedItemId().isBlank()) {
            try {
                id = Long.parseLong(input.bannedItemId());
            } catch (NumberFormatException invalid) {
                throw new BusinessError("INPUT_INVALID", 422, "禁发条目标识无效");
            }
        }
        return new Validated(id, input.group(), content, input.displayOrder());
    }

    private record Validated(Long id, String group, String content, int displayOrder) {
    }

    public record Input(String bannedItemId, String group, String content, Integer displayOrder) {
    }

    public record ItemView(String id, String content, int displayOrder) {
    }

    public record GroupView(String group, List<ItemView> items) {
    }

    public record BannedScopeView(Instant updatedAt, List<GroupView> groups) {
    }
}
