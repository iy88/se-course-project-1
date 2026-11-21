ALTER TABLE file_record
    DROP COLUMN content_sha256,
    ADD CONSTRAINT file_record_verified_metadata_check
        CHECK (num_nonnulls(verified_at, content_etag, verified_size, verified_content_type) IN (0, 4));
