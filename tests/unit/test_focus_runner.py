"""focus_runner's version-aware oracle selection: use `oracles(version)` when a focus module
defines it, else keep using its `ORACLES` attribute unconditionally."""
from dev import focus_append, focus_r11, focus_rename, focus_runner, dev_focus


def test_version_aware_selection_for_focus_rename():
    assert focus_runner.oracles_for(focus_rename, 6) == focus_rename.ORACLES_V6
    assert focus_runner.oracles_for(focus_rename, 8) == {}


def test_modules_without_oracles_function_use_module_oracles_unconditionally():
    assert getattr(dev_focus, 'oracles', None) is None
    assert focus_runner.oracles_for(dev_focus, 3) is dev_focus.ORACLES
    assert focus_runner.oracles_for(dev_focus, 8) is dev_focus.ORACLES

    assert getattr(focus_r11, 'oracles', None) is None
    assert focus_runner.oracles_for(focus_r11, 3) is focus_r11.ORACLES

    assert getattr(focus_append, 'oracles', None) is None
    assert focus_runner.oracles_for(focus_append, 7) is focus_append.ORACLES


def test_sets_registers_rename():
    assert focus_runner.SETS['rename'] == 'dev.focus_rename'
