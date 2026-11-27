DELETE FROM notification n
USING moderation_case_action a
WHERE n.source_type = 'case' AND n.source_id = a.case_id
  AND a.actor_kind = 'manager' AND n.recipient_account_id = a.actor_account_id
  AND a.action_kind IN ('decide', 'execute', 'lift')
  AND n.event_type = 'management.case_' || a.action_kind
  AND (n.intent_key = 'management:case:' || a.case_id || ':action:' || a.id
       OR (a.action_kind = 'decide' AND n.intent_key = 'management:case:' || a.case_id || ':review:decide'));
