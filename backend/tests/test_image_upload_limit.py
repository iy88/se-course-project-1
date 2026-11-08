"""Application image limits and removal of the old database constraint."""
import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect, text

from app.api.v1.files import LeaseRequest
from app.db.migrations import drop_upload_size_constraint
from app.storage.images import MAX_IMAGE_BYTES


def test_lease_size_boundary():
    assert MAX_IMAGE_BYTES == 100 * 1024 * 1024
    args = dict(namespace='product', filename='large.jpg', content_type='image/jpeg', sha256='a' * 64)
    assert LeaseRequest(**args, size_bytes=MAX_IMAGE_BYTES).size_bytes == MAX_IMAGE_BYTES
    with pytest.raises(ValidationError):
        LeaseRequest(**args, size_bytes=MAX_IMAGE_BYTES + 1)


def test_sqlite_existing_lease_limit_upgrade_preserves_rows():
    engine = create_engine('sqlite:///:memory:')
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE upload_leases (id TEXT PRIMARY KEY, size_bytes INTEGER NOT NULL, CONSTRAINT ck_upload_leases_upload_size_allowed CHECK (size_bytes > 0 AND size_bytes <= 10485760))'))
        conn.execute(text("INSERT INTO upload_leases VALUES ('old', 10)"))
        drop_upload_size_constraint(conn)
        drop_upload_size_constraint(conn)
        assert conn.scalar(text("SELECT size_bytes FROM upload_leases WHERE id='old'")) == 10
        conn.execute(text("INSERT INTO upload_leases VALUES ('large', 104857600)"))
        # Database storage no longer defines image size policy; the API enforces it.
        conn.execute(text("INSERT INTO upload_leases VALUES ('above_policy', 104857601)"))
        assert inspect(conn).get_check_constraints('upload_leases') == []


def test_image_above_previous_limit_is_valid():
    from io import BytesIO
    from PIL import Image
    from app.storage.images import validate_image

    buffer = BytesIO()
    Image.new('RGB', (1, 1)).save(buffer, format='JPEG')
    content = buffer.getvalue() + b'\0' * (11 * 1024 * 1024)
    assert validate_image(content, 'large.jpg') == 'image/jpeg'
