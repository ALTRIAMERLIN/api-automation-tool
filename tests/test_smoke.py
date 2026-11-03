import apitool
from apitool import cli


def test_version_constant():
    assert apitool.__version__ == "1.0.0"


def test_version_flag_prints_version(capsys):
    assert cli.main(["--version"]) == 0
    assert capsys.readouterr().out == "apitool 1.0.0\n"
