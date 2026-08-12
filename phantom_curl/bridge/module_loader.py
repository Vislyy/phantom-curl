"""A small, same-origin loader for the supported subset of ES modules."""

from __future__ import annotations

import json
import re
from urllib.parse import urljoin, urlsplit

from phantom_curl.engine.context import JSContext
from phantom_curl.exceptions import InterceptorError
from phantom_curl.network.session import NetworkSession
from phantom_curl.utils.request_builder import build_request_options


class ModuleLoader:
    """Load and execute static same-origin JavaScript modules for one page."""

    _IMPORT_FROM_RE = re.compile(
        r"^\s*import\s+(?P<clause>[^;\n]+?)\s+from\s+(?P<quote>['\"])(?P<specifier>[^'\"]+)(?P=quote)\s*;?",
        re.MULTILINE,
    )
    _IMPORT_SIDE_EFFECT_RE = re.compile(
        r"^\s*import\s+(?P<quote>['\"])(?P<specifier>[^'\"]+)(?P=quote)\s*;?",
        re.MULTILINE,
    )
    _EXPORT_DECLARATION_RE = re.compile(
        r"(?:^|(?<=;))\s*export\s+(?P<kind>const|let|var|function|class)\s+(?P<name>[A-Za-z_$][\w$]*)",
        re.MULTILINE,
    )
    _EXPORT_LIST_RE = re.compile(r"(?:^|(?<=;))\s*export\s*\{(?P<bindings>[^}]+)\}\s*;?", re.MULTILINE)
    _EXPORT_DEFAULT_RE = re.compile(
        r"(?:^|(?<=;))\s*export\s+default\s+(?P<expression>[^;\n]+);?", re.MULTILINE
    )
    _IDENTIFIER_RE = re.compile(r"^[A-Za-z_$][\w$]*$")

    def __init__(self, context: JSContext, session: NetworkSession, page_url: str) -> None:
        self._context = context
        self._session = session
        self._page_url = page_url
        self._registered_modules: set[str] = set()

        self._context.eval(
            """
            globalThis.__phantom_module_exports = Object.create(null);
            globalThis.__phantom_module_factories = Object.create(null);

            globalThis.__phantom_require = function (url) {
                if (Object.prototype.hasOwnProperty.call(globalThis.__phantom_module_exports, url)) {
                    return globalThis.__phantom_module_exports[url];
                }

                const factory = globalThis.__phantom_module_factories[url];
                if (!factory) {
                    throw new Error('PhantomCurl module was not registered: ' + url);
                }

                const exports = Object.create(null);
                globalThis.__phantom_module_exports[url] = exports;
                factory(exports, globalThis.__phantom_require);
                return exports;
            };
            """
        )

    def execute_inline(self, source: str, node_id: str) -> None:
        """Transform and execute an inline module with a stable page-local URL."""
        module_url = f"{self._page_url}#inline-{node_id}"
        self._register_module(module_url, source)
        self._execute_module(module_url)

    def execute_external(self, source_url: str) -> None:
        """Fetch, transform and execute an external module script."""
        module_url = self._resolve_url(source_url, self._page_url)
        self._register_module(module_url, self._fetch_module(module_url, self._page_url))
        self._execute_module(module_url)

    def _register_module(self, module_url: str, source: str) -> None:
        if module_url in self._registered_modules:
            return

        self._registered_modules.add(module_url)
        transformed_source, dependencies = self._transform(source, module_url)
        self._context.eval(
            "globalThis.__phantom_module_factories["
            f"{json.dumps(module_url)}"
            "] = function (exports, __require) {\n"
            f"{transformed_source}\n"
            "};"
        )

        for dependency_url in dependencies:
            if dependency_url not in self._registered_modules:
                self._register_module(dependency_url, self._fetch_module(dependency_url, module_url))

    def _execute_module(self, module_url: str) -> None:
        self._context.eval(f"globalThis.__phantom_require({json.dumps(module_url)});")

    def _transform(self, source: str, module_url: str) -> tuple[str, list[str]]:
        dependencies: list[str] = []
        exports: list[tuple[str, str]] = []

        def import_from(match: re.Match[str]) -> str:
            dependency_url = self._resolve_url(match.group("specifier"), module_url)
            dependencies.append(dependency_url)
            return self._translate_import(match.group("clause"), dependency_url)

        source = self._IMPORT_FROM_RE.sub(import_from, source)

        def import_side_effect(match: re.Match[str]) -> str:
            dependency_url = self._resolve_url(match.group("specifier"), module_url)
            dependencies.append(dependency_url)
            return f"__require({json.dumps(dependency_url)});"

        source = self._IMPORT_SIDE_EFFECT_RE.sub(import_side_effect, source)

        def export_declaration(match: re.Match[str]) -> str:
            name = match.group("name")
            exports.append((name, name))
            return f"{match.group('kind')} {name}"

        source = self._EXPORT_DECLARATION_RE.sub(export_declaration, source)

        def export_list(match: re.Match[str]) -> str:
            for binding in match.group("bindings").split(","):
                local_name, export_name = self._parse_export_binding(binding)
                exports.append((local_name, export_name))
            return ""

        source = self._EXPORT_LIST_RE.sub(export_list, source)

        def export_default(match: re.Match[str]) -> str:
            exports.append(("__phantom_default_export", "default"))
            return f"const __phantom_default_export = {match.group('expression')};"

        source = self._EXPORT_DEFAULT_RE.sub(export_default, source)

        assignments = "\n".join(
            f"exports[{json.dumps(export_name)}] = {local_name};" for local_name, export_name in exports
        )
        return f"{source}\n{assignments}", dependencies

    def _translate_import(self, clause: str, dependency_url: str) -> str:
        clause = clause.strip()
        require = f"__require({json.dumps(dependency_url)})"

        if clause.startswith("{") and clause.endswith("}"):
            return f"const {self._translate_named_imports(clause)} = {require};"
        if clause.startswith("* as "):
            namespace = clause.removeprefix("* as ").strip()
            self._require_identifier(namespace, "namespace import")
            return f"const {namespace} = {require};"
        if "," in clause:
            default_name, remainder = clause.split(",", 1)
            self._require_identifier(default_name.strip(), "default import")
            named_import = self._translate_import(remainder.strip(), dependency_url)
            return f"const {default_name.strip()} = {require}.default;\n{named_import}"

        self._require_identifier(clause, "default import")
        return f"const {clause} = {require}.default;"

    def _translate_named_imports(self, clause: str) -> str:
        bindings: list[str] = []
        for binding in clause[1:-1].split(","):
            original_name, local_name = self._parse_import_binding(binding)
            bindings.append(original_name if original_name == local_name else f"{original_name}: {local_name}")
        return "{" + ", ".join(bindings) + "}"

    def _parse_import_binding(self, binding: str) -> tuple[str, str]:
        parts = re.split(r"\s+as\s+", binding.strip())
        if len(parts) not in {1, 2}:
            raise InterceptorError(f"Unsupported module import binding: {binding!r}")
        original_name = parts[0].strip()
        local_name = parts[-1].strip()
        self._require_identifier(original_name, "imported name")
        self._require_identifier(local_name, "local import name")
        return original_name, local_name

    def _parse_export_binding(self, binding: str) -> tuple[str, str]:
        parts = re.split(r"\s+as\s+", binding.strip())
        if len(parts) not in {1, 2}:
            raise InterceptorError(f"Unsupported module export binding: {binding!r}")
        local_name = parts[0].strip()
        export_name = parts[-1].strip()
        self._require_identifier(local_name, "local export name")
        self._require_identifier(export_name, "exported name")
        return local_name, export_name

    def _resolve_url(self, requested_url: str, importer_url: str) -> str:
        module_url = urljoin(importer_url, requested_url)
        if self._origin(module_url) != self._origin(self._page_url):
            raise InterceptorError(
                f"Module {module_url!r} imported by {importer_url!r} is outside the page's same-origin boundary"
            )
        return module_url

    def _fetch_module(self, module_url: str, importer_url: str) -> str:
        response = self._session.request(
            build_request_options(
                method="GET",
                url=module_url,
                headers={"Referer": importer_url},
                allow_redirects=False,
            )
        )
        if response.status_code >= 400:
            raise InterceptorError(
                f"Failed to load module {module_url!r} imported by {importer_url!r}: HTTP {response.status_code}"
            )
        return response.text

    @staticmethod
    def _origin(url: str) -> tuple[str, str, int]:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
            raise InterceptorError("Module URLs must resolve to an HTTP or HTTPS origin")
        try:
            port = parsed.port
        except ValueError as error:
            raise InterceptorError("Module URL contains an invalid port") from error

        return parsed.scheme.lower(), parsed.hostname.lower(), port or (443 if parsed.scheme == "https" else 80)

    @classmethod
    def _require_identifier(cls, value: str, description: str) -> None:
        if not cls._IDENTIFIER_RE.fullmatch(value):
            raise InterceptorError(f"Unsupported {description}: {value!r}")