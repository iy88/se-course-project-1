-- Repair product-comment notifications that predate the synchronous notification listener.
--
-- New writes create these rows in the comment transaction. This migration only fills missing
-- notification facts; it does not emit historical realtime events or mark anything as read.

INSERT INTO notification (
    recipient_account_id,
    intent_key,
    event_type,
    business_event_id,
    source_type,
    source_id,
    template_key,
    template_version,
    display_params,
    occurred_at,
    created_at,
    read_at
)
SELECT
    product.seller_account_id,
    'product_comment.created:' || top_comment.comment_id,
    'product_comment.created',
    NULL,
    'product',
    top_comment.product_id,
    'product_comment.created',
    '1',
    '{"values": {}}'::jsonb,
    top_comment.created_at,
    now(),
    NULL
FROM product_comment top_comment
JOIN product ON product.product_id = top_comment.product_id
WHERE top_comment.parent_comment_id IS NULL
  AND top_comment.author_account_id <> product.seller_account_id
  AND top_comment.deleted_at IS NULL
  AND top_comment.removed_at IS NULL
  AND NOT EXISTS (
      SELECT 1
      FROM notification existing
      WHERE existing.recipient_account_id = product.seller_account_id
        AND existing.intent_key = 'product_comment.created:' || top_comment.comment_id
  );

INSERT INTO notification (
    recipient_account_id,
    intent_key,
    event_type,
    business_event_id,
    source_type,
    source_id,
    template_key,
    template_version,
    display_params,
    occurred_at,
    created_at,
    read_at
)
SELECT
    parent.author_account_id,
    'product_comment.replied:' || reply.comment_id,
    'product_comment.replied',
    NULL,
    'product',
    reply.product_id,
    'product_comment.replied',
    '1',
    '{"values": {}}'::jsonb,
    reply.created_at,
    now(),
    NULL
FROM product_comment reply
JOIN product_comment parent ON parent.comment_id = reply.parent_comment_id
WHERE reply.parent_comment_id IS NOT NULL
  AND parent.author_account_id <> reply.author_account_id
  AND reply.deleted_at IS NULL
  AND reply.removed_at IS NULL
  AND NOT EXISTS (
      SELECT 1
      FROM notification existing
      WHERE existing.recipient_account_id = parent.author_account_id
        AND existing.intent_key = 'product_comment.replied:' || reply.comment_id
  );
