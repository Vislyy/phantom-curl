import pytest

from phantom_curl.engine.context import JSContext
from phantom_curl.engine.dom_builder import DOMBuilder
from phantom_curl.exceptions import JSRuntimeError


def test_dom_builder_collects_scripts_with_normalized_types() -> None:
    builder = DOMBuilder(JSContext())
    builder.parse_html(
        """
        <script type=" Text/JavaScript ">window.inlineRan = true;</script>
        <script src="/static/app.js" type="application/javascript"></script>
        """
    )

    scripts = builder.get_scripts()

    assert [script["script_type"] for script in scripts] == ["inline", "external"]
    assert [script["code_type"] for script in scripts] == ["text/javascript", "application/javascript"]
    assert builder.get_inline_scripts() == ["window.inlineRan = true;"]
    assert builder.get_external_scripts() == ["/static/app.js"]


def test_quickjs_context_rejects_esm_export_in_classic_script_mode() -> None:
    context = JSContext()

    with pytest.raises(JSRuntimeError, match="unsupported keyword: export"):
        context.eval("export const token = 1")
