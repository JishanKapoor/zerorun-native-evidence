import copy
import sys
from types import ModuleType

import pytest

from zerorun_harness.api import InvalidEvidence
from zerorun_harness.binding import generate_binding, recorder
from zerorun_harness.batches import extract_batches
from zerorun_harness.records import register_records
from test_native_projection import one_site

MODEL = '''class Score:
    sample_id: str
    value: int
    def __init__(self, sample_id, value):
        self.sample_id = sample_id
        self.value = value
'''
SOURCE = 'def outer(scores):\n native = scores[:]\n return native\n'


def setup_profile():
    p = one_site('outer', 'native = scores[:]', 'after',
                 {'item': True, 'path': [{'stored': 'value', 'record': 'score'}]})
    p['identity']['sample_id'] = 'str'
    p['rules'][0]['keys'].append('sample_id')
    p['sites']['return']['batch'] = {'local': 'native', 'max_items': 64, 'ordinal': 'acquisition'}
    p['sites']['return']['projection']['sample_id'] = {
        'item': True, 'path': [{'stored': 'sample_id', 'record': 'score'}]}
    p['record_types'] = {'score': {'module': 'native_model', 'name': 'Score',
        'path': 'native_model.py', 'fields': ['sample_id', 'value']}}
    return p


def capture(monkeypatch, samples):
    p = setup_profile()
    b = generate_binding(p, {'native.py': SOURCE, 'native_model.py': MODEL}, grammar_version='1.3.0')
    module = ModuleType('native_model')
    exec(MODEL, module.__dict__)
    monkeypatch.setitem(sys.modules, 'native_model', module)
    registry = register_records(p, b, {'score': module.Score})
    raw = []
    class Sink:
        def emit(self, item):
            raw.append(copy.deepcopy(item))
            return True
    scope = {'__zr_observe': recorder(p, b, Sink(), 123, records=registry)}
    exec(b['transformed']['native.py'], scope)
    inputs = [module.Score(*row) for row in samples]
    result = scope['outer'](inputs)
    assert result == inputs and result is not inputs
    return p, b, raw


@pytest.mark.parametrize('samples', [[], [('second', 0)], [('second', 0), ('first', 1)]])
def test_actual_item_identity_and_acquisition_order_are_distinct(monkeypatch, samples):
    p, b, raw = capture(monkeypatch, samples)
    result = extract_batches(p, b, raw)
    assert result['batches'][0]['complete']
    assert 'sample_id' not in result['batches'][0]['identity']
    assert [e['identity']['sample_id'] for e in result['events']] == [x[0] for x in samples]
    assert [e['acquisition']['ordinal'] for e in result['events']] == list(range(len(samples)))
    assert all(e['identity']['obligation'] == 0 for e in result['events'])


@pytest.mark.parametrize('damage', ['ordinal', 'batch', 'missing', 'extra', 'typed'])
def test_acquisition_metadata_damage_never_supplies_complete_batch(monkeypatch, damage):
    p, b, raw = capture(monkeypatch, [('first', 1), ('second', 0)])
    if damage == 'ordinal':
        raw[2]['acquisition']['ordinal'] = 0
        assert extract_batches(p, b, raw)['batches'][0]['complete'] is False
        return
    if damage == 'batch':
        raw[1]['acquisition']['batch'] += 1
    elif damage == 'missing':
        del raw[1]['acquisition']
    elif damage == 'extra':
        raw[1]['acquisition']['inferred'] = True
    else:
        raw[1]['acquisition']['ordinal'] = False
    with pytest.raises(InvalidEvidence):
        extract_batches(p, b, raw)


def test_lost_actual_item_remains_incomplete(monkeypatch):
    p, b, raw = capture(monkeypatch, [('first', 1), ('second', 0)])
    del raw[1]
    result = extract_batches(p, b, raw)
    assert result['batches'][0]['complete'] is False
    assert result['events'][0]['identity']['sample_id'] == 'second'


@pytest.mark.parametrize('version', ['1.0.0', '1.1.0', '1.2.0'])
def test_old_grammars_cannot_silently_adopt_item_identity(version):
    with pytest.raises(InvalidEvidence, match='Old grammar'):
        generate_binding(setup_profile(), {'native.py': SOURCE, 'native_model.py': MODEL}, grammar_version=version)


@pytest.mark.parametrize('projection', [{'item': True}, {'item': True, 'path': [{'index': 0}]},
    {'item': True, 'path': [{'stored': 'sample_id', 'record': 'score'}], 'encoding': 'json'}])
def test_scientific_item_identity_requires_unconverted_native_storage(projection):
    p = setup_profile(); p['sites']['return']['projection']['sample_id'] = projection
    with pytest.raises(InvalidEvidence):
        generate_binding(p, {'native.py': SOURCE, 'native_model.py': MODEL}, grammar_version='1.3.0')


def test_acquisition_ordinal_not_also_in_scientific_identity():
    p = setup_profile(); p['sites']['return']['projection']['obligation'] = {'ordinal': True}
    with pytest.raises(InvalidEvidence):
        generate_binding(p, {'native.py': SOURCE, 'native_model.py': MODEL}, grammar_version='1.3.0')
