import seetapsych_lib as pkg


def test_import_and_version():
    print(f"Package: {pkg.__name__}")
    print(f"Version: {pkg.__version__}")
    assert isinstance(pkg.__version__, str)
    assert len(pkg.__version__) > 0
