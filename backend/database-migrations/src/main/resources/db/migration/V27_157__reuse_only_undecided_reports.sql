DROP INDEX moderation_case_open_report_object;
DROP INDEX moderation_case_open_report_message;

-- One open report per reporter and object; message targets additionally separate their branch.
CREATE UNIQUE INDEX moderation_case_open_report_object
    ON moderation_case (reporter_account_id, target_type, target_id)
    WHERE archived_at IS NULL AND case_status IN ('pending', 'claimed') AND case_type = 'report' AND target_type <> 'message';

CREATE UNIQUE INDEX moderation_case_open_report_message
    ON moderation_case (reporter_account_id, target_conversation_kind, target_id)
    WHERE archived_at IS NULL AND case_status IN ('pending', 'claimed') AND case_type = 'report' AND target_type = 'message';
