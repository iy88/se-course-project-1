-- Earlier standalone product submissions reserved a case ID without opening the case.
INSERT INTO moderation_case (id, case_type, created_at)
SELECT case_id, 'product_review', submitted_at
FROM product_audit
ON CONFLICT (id) DO NOTHING;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM product_audit a
        JOIN moderation_case c ON c.id = a.case_id
        WHERE c.case_type <> 'product_review'
    ) THEN
        RAISE EXCEPTION 'Existing product audit links to a different case type';
    END IF;
END $$;

SELECT setval(pg_get_serial_sequence('moderation_case', 'id'),
              greatest(coalesce((SELECT max(id) + 1 FROM moderation_case), 1),
                       nextval(pg_get_serial_sequence('moderation_case', 'id'))),
              false);
