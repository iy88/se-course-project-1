"""Unicode 17 conformance and business validation; no external resources."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import create_engine, text

from app.core.text import NonBlank64, NonBlank2000, TextLimit, grapheme_count, normalize_text
from app.api.v1.comments import CommentIn
from app.api.v1.my_cases import StatementIn
from app.api.v1.admin.cases import InquiryIn, CaseMessageIn

ROOT = Path(__file__).resolve().parents[2]


def test_shared_text_examples():
    for case in json.loads((ROOT / 'frontend/shared/text_cases.json').read_text()):
        value = normalize_text(case['text'])
        assert grapheme_count(value) == case['count']
        assert value == case.get('normalized', case['text'])


def test_unicode_official_boundaries():
    from app.core.text import _GRAPHEME
    cases = 0
    for line in (Path(__file__).parent / 'fixtures/GraphemeBreakTest-17.0.0.txt').read_text().splitlines():
        tokens = line.split('#')[0].split()
        if not tokens:
            continue
        expected = []
        segment = ''
        for token in tokens:
            if token == '÷':
                if segment:
                    expected.append(segment)
                    segment = ''
            elif token != '×':
                segment += chr(int(token, 16))
        assert _GRAPHEME.findall(''.join(expected)) == expected, line
        cases += 1
    assert cases > 500


@pytest.mark.parametrize('model', [CommentIn, StatementIn, InquiryIn, CaseMessageIn])
def test_exact_limit_is_accepted_and_excess_rejected(model):
    value = '👨‍👩‍👧‍👦' * 2000
    assert model(content=value).content == value
    with pytest.raises(ValidationError):
        model(content=value + '中')
    with pytest.raises(ValidationError):
        model(content=' \t ')
    assert 'maxLength' not in model.model_json_schema()['properties']['content']
    assert model.model_json_schema()['properties']['content']['x-max-graphemes'] == 2000


def test_utf8_budget_and_invalid_surrogate():
    adapter = TypeAdapter(NonBlank2000)
    for value in ['a' + '\u0301' * 40000, '\ud800']:
        with pytest.raises(ValidationError):
            adapter.validate_python(value)
    name = '👨‍👩‍👧‍👦' * 64
    assert TypeAdapter(NonBlank64).validate_python(name) == name
    assert TextLimit(2000).validate('  a\r\nb  ') == 'a\nb'


def test_migration_widens_without_truncation_and_refuses_lossy_downgrade(monkeypatch):
    path = ROOT / 'backend/alembic/versions/d1e2f3a4b5c6_human_text_graphemes.py'
    spec = importlib.util.spec_from_file_location('text_migration', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls = []
    connection = SimpleNamespace(dialect=SimpleNamespace(name='postgresql'), scalar=lambda query: 0)
    monkeypatch.setattr(module, 'op', SimpleNamespace(get_bind=lambda: connection, alter_column=lambda *a, **kw: calls.append((a, kw))))
    module.upgrade()
    assert len(calls) == len(module.COLUMNS)
    calls.clear()
    connection.scalar = lambda query: 1
    with pytest.raises(RuntimeError, match='downgrade refused'):
        module.downgrade()
    assert calls == []
    # SQLite must remain additive: no table rebuild or destructive conversion.
    connection.dialect.name = 'sqlite'
    module.upgrade()
    module.downgrade()
    assert calls == []


def test_database_human_short_fields_accept_compound_characters():
    from app.db.session import Base
    from app.models import User
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    value = '👨‍👩‍👧‍👦' * 64
    with engine.begin() as connection:
        connection.execute(User.__table__.insert().values(email='unicode@example.com', display_name=value, password_hash='x'))
        assert connection.execute(text('select display_name from users')).scalar_one() == value
    assert str(User.__table__.c.display_name.type) == 'TEXT'
    engine.dispose()
