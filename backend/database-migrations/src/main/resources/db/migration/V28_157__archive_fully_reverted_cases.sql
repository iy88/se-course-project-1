WITH archived AS (
    UPDATE moderation_case c
       SET archived_at = statement_timestamp(), updated_at = statement_timestamp()
     WHERE c.case_status = 'decided' AND c.archived_at IS NULL
       AND EXISTS (
           SELECT 1 FROM case_enforcement e
            WHERE e.case_id = c.id AND e.result_status IN ('applied', 'replayed')
              AND e.action NOT IN ('lift_account_restriction', 'restore_display', 'lift_trade_freeze')
       )
       AND NOT EXISTS (
           SELECT 1 FROM case_enforcement e
            WHERE e.case_id = c.id AND e.result_status IN ('applied', 'replayed')
              AND e.action NOT IN ('lift_account_restriction', 'restore_display', 'lift_trade_freeze')
              AND e.lifted_at IS NULL
       )
       AND NOT EXISTS (
           SELECT 1 FROM moderation_case_action a
            WHERE a.case_id = c.id AND a.action_kind = 'appeal'
              AND NOT EXISTS (
                  SELECT 1 FROM moderation_case_action r
                   WHERE r.case_id = c.id AND r.action_kind = 'manager_reply' AND r.appeal_action_id = a.id
              )
       )
     RETURNING c.id, c.archived_at
), archived_threads AS (
    UPDATE case_conversation t
       SET archived_at = a.archived_at
      FROM archived a
     WHERE t.case_id = a.id AND t.archived_at IS NULL
)
INSERT INTO moderation_case_action (case_id, action_kind, actor_kind, occurred_at)
SELECT id, 'close', 'system', archived_at FROM archived;
