ALTER TABLE file_record DROP CONSTRAINT file_record_purpose_check;
ALTER TABLE file_record ADD CONSTRAINT file_record_purpose_check
    CHECK (purpose IN ('product_image', 'case_evidence', 'account_avatar'));
