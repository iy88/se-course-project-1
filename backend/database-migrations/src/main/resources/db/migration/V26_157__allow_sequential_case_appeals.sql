DROP INDEX moderation_case_action_appeal_once;

CREATE INDEX moderation_case_action_appeal_by_account
    ON moderation_case_action (case_id, actor_account_id, id DESC)
    WHERE action_kind = 'appeal';
