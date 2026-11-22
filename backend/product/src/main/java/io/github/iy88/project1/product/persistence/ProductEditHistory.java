package io.github.iy88.project1.product.persistence;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Instant;
import java.util.Map;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

@Entity
@Table(name = "product_edit_history")
public class ProductEditHistory {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "edit_id")
    private Long id;

    @Column(name = "product_id", nullable = false)
    private long productId;

    @Column(name = "operator_kind", nullable = false)
    private String operatorKind;

    @Column(name = "operator_account_id", nullable = false)
    private long operatorAccountId;

    @Column(name = "edit_kind", nullable = false)
    private String editKind;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "before_content", nullable = false)
    private Map<String, Object> beforeContent;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "after_content", nullable = false)
    private Map<String, Object> afterContent;

    @Column(name = "reason")
    private String reason;

    @Column(name = "edited_at", nullable = false)
    private Instant editedAt;

    protected ProductEditHistory() {
    }

    public ProductEditHistory(long productId, long operatorAccountId, Map<String, Object> beforeContent,
                              Map<String, Object> afterContent, Instant now) {
        this.productId = productId;
        this.operatorKind = "seller";
        this.operatorAccountId = operatorAccountId;
        this.editKind = "content_edit";
        this.beforeContent = beforeContent;
        this.afterContent = afterContent;
        this.editedAt = now;
    }

    public long id() { return id; }
    public String operatorKind() { return operatorKind; }
    public String editKind() { return editKind; }
    public Map<String, Object> beforeContent() { return beforeContent; }
    public Map<String, Object> afterContent() { return afterContent; }
    public String reason() { return reason; }
    public Instant editedAt() { return editedAt; }
}
