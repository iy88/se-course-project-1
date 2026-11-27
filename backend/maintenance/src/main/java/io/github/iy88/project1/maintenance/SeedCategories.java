package io.github.iy88.project1.maintenance;

import java.sql.SQLException;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;

/** Category tree shared by both seed modes. Names and aliases follow the current category contract. */
final class SeedCategories {
    record Definition(String name, List<String> aliases) {
    }

    static final List<Definition> LOAD = List.of(
            new Definition("数码电子", List.of("电子产品", "数码")),
            new Definition("教材书籍", List.of("课本")),
            new Definition("运动户外", List.of("球类")),
            new Definition("生活家居", List.of("宿舍好物")),
            new Definition("骑行装备", List.of()));

    private SeedCategories() {
    }

    static List<Long> create(SeedDatabase database, SeedContext context, long managerId, Instant now,
                             List<Definition> definitions) throws SQLException {
        List<Long> ids = new ArrayList<>();
        for (Definition definition : definitions) {
            long categoryId = database.insert("""
                    insert into category (created_by_admin_id, created_at)
                    values (?, ?)
                    returning category_id
                    """, managerId, now.minusSeconds(90L * 86_400));
            database.update("""
                    insert into category_name (category_id, name, name_kind, created_at)
                    values (?, ?, 'main', ?)
                    """, categoryId, definition.name(), now.minusSeconds(90L * 86_400));
            for (String alias : definition.aliases()) {
                database.update("""
                        insert into category_name (category_id, name, name_kind, created_at)
                        values (?, ?, 'alias', ?)
                        """, categoryId, alias, now.minusSeconds(80L * 86_400));
            }
            ids.add(categoryId);
        }
        return List.copyOf(ids);
    }
}
