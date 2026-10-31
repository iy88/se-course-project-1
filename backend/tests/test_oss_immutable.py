"""Offline checks for immutable OSS writes; no external services are contacted."""
import pytest
from app.storage.base import StorageAlreadyExists, StoragePermissionDenied
from app.storage.oss import OssConfig, OssStorage, _V2Bucket


def test_v2_adapter_passes_forbid_overwrite():
    class Client:
        def put_object(self, request):
            self.request = request

    client = Client()
    _V2Bucket(client, 'media').put_object(
        'prefix/product/a.jpg', b'content',
        {'Content-Type': 'image/jpeg', 'x-oss-forbid-overwrite': 'true'},
    )
    assert client.request.bucket == 'media'
    assert client.request.forbid_overwrite is True
    assert client.request.content_type == 'image/jpeg'


def test_save_to_key_uses_role_prefix_and_refuses_overwrite():
    class Conflict(Exception):
        code = 'FileAlreadyExists'
        status_code = 409

    class Bucket:
        def __init__(self):
            self.calls = []

        def put_object(self, key, content, headers):
            self.calls.append((key, content, headers))
            if len(self.calls) > 1:
                raise Conflict()

    buckets = {}
    def factory(_config, name):
        return buckets.setdefault(name, Bucket())

    config = OssConfig(region='region', endpoint='https://example.com', media_bucket='media',
                       evidence_bucket='evidence', access_key_id='id', access_key_secret='secret',
                       key_prefix='demo', max_retries=2)
    storage = OssStorage(config, factory)
    storage.save_to_key('report/test/evidence.jpg', b'content')
    assert buckets['evidence'].calls == [('demo/report/test/evidence.jpg', b'content',
        {'Content-Type': 'image/jpeg', 'x-oss-forbid-overwrite': 'true'})]
    with pytest.raises(StorageAlreadyExists):
        storage.save_to_key('report/test/evidence.jpg', b'other')
    assert len(buckets['evidence'].calls) == 2
    storage.save_to_key('product/test/photo.png', b'photo')
    assert buckets['media'].calls[0][0] == 'demo/product/test/photo.png'
    assert buckets['media'].calls[0][2]['Content-Type'] == 'image/png'


@pytest.mark.parametrize('status,code', [(404, 'NoSuchKey'), (403, 'AccessDenied')])
def test_exists_distinguishes_expected_missing_from_permission_failure(caplog, status, code):
    from alibabacloud_oss_v2.exceptions import OperationError, ServiceError

    class Bucket:
        def head_object(self, _key):
            error = ServiceError(status_code=status, code=code, request_id='test', message='test',
                                 ec='test', timestamp='test', request_target='private-target')
            raise OperationError(name='HeadObject', error=error)

    config = OssConfig(region='region', endpoint='https://example.com', media_bucket='media',
                       evidence_bucket='evidence', access_key_id='id', access_key_secret='secret')
    storage = OssStorage(config, lambda _config, _name: Bucket())
    if status == 404:
        assert storage.exists('product/test/image.jpg') is False
        assert not caplog.records
    else:
        with pytest.raises(StoragePermissionDenied):
            storage.exists('product/test/image.jpg')
        assert 'status=403 code=AccessDenied' in caplog.text
        assert 'private-target' not in caplog.text
