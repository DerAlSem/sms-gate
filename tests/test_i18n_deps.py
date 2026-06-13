# tests/test_i18n_deps.py
def test_web_and_i18n_stack_importable():
    import fastapi          # noqa: F401
    import jinja2           # noqa: F401
    import babel            # noqa: F401
    from babel.messages.pofile import read_po   # noqa: F401
    from babel.messages.mofile import write_mo   # noqa: F401
