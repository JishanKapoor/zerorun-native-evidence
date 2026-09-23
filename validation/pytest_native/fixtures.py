"""Fixed authored source, selected before native execution."""

TEST_SOURCE = '''import pytest

def test_pass():
    assert 2 + 2 == 4

def test_fail():
    assert False, "authored call failure"

def test_skip():
    pytest.skip("authored call skip")

@pytest.mark.xfail(reason="authored expected failure")
def test_xfail():
    assert False

@pytest.mark.xfail(reason="authored unexpected pass", strict=False)
def test_xpass():
    assert True

@pytest.fixture
def broken_setup():
    raise RuntimeError("authored setup error")

def test_setup_error(broken_setup):
    assert True

@pytest.fixture
def broken_teardown():
    yield
    raise RuntimeError("authored teardown error")

def test_teardown_error(broken_teardown):
    assert True

@pytest.fixture
def broken_both(request):
    def finalizer():
        raise RuntimeError("authored second phase error")
    request.addfinalizer(finalizer)
    raise RuntimeError("authored first phase error")

def test_two_phase_errors(broken_both):
    assert True

@pytest.mark.parametrize("number", [1, 2], ids=["one", "two"])
def test_parameter(number):
    assert number > 0
'''

EXPECTED = {
    'test_pass': [('setup', 'passed'), ('call', 'passed'), ('teardown', 'passed')],
    'test_fail': [('setup', 'passed'), ('call', 'failed'), ('teardown', 'passed')],
    'test_skip': [('setup', 'passed'), ('call', 'skipped'), ('teardown', 'passed')],
    'test_xfail': [('setup', 'passed'), ('call', 'skipped'), ('teardown', 'passed')],
    'test_xpass': [('setup', 'passed'), ('call', 'passed'), ('teardown', 'passed')],
    'test_setup_error': [('setup', 'failed'), ('teardown', 'passed')],
    'test_teardown_error': [('setup', 'passed'), ('call', 'passed'), ('teardown', 'failed')],
    'test_two_phase_errors': [('setup', 'failed'), ('teardown', 'failed')],
    'test_parameter[one]': [('setup', 'passed'), ('call', 'passed'), ('teardown', 'passed')],
    'test_parameter[two]': [('setup', 'passed'), ('call', 'passed'), ('teardown', 'passed')],
}
