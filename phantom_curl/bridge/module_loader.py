"""A small static ES-module loader with explicit cross-origin controls."""

from __future__ import annotations

import json
import re
from urllib.parse import urljoin, urlsplit

from phantom_curl.engine.context import JSContext
from phantom_curl.exceptions import InterceptorError, JSRuntimeError
from phantom_curl.models import OriginPolicy
from phantom_curl.network.session import NetworkSession
from phantom_curl.utils.request_builder import build_request_options


class ModuleLoader:
    """Load and execute supported static JavaScript modules for one page."""

    _IMPORT_FROM_RE = re.compile(
        r"(?:^|(?<=[;}]))\s*import\s*(?P<clause>[^;\n]+?)\s*from\s*(?P<quote>['\"])(?P<specifier>[^'\"]+)(?P=quote)\s*;?",
        re.MULTILINE,
    )
    _IMPORT_SIDE_EFFECT_RE = re.compile(
        r"(?:^|(?<=[;}]))\s*import\s*(?P<quote>['\"])(?P<specifier>[^'\"]+)(?P=quote)\s*;?",
        re.MULTILINE,
    )
    _EXPORT_DECLARATION_RE = re.compile(
        r"(?:^|(?<=[;}]))\s*export\s+(?P<kind>const|let|var|(?:async\s+)?function|class)\s+(?P<name>[A-Za-z_$][\w$]*)",
        re.MULTILINE,
    )
    _EXPORT_FROM_RE = re.compile(
        r"(?:^|(?<=[;}]))\s*export\s*\{\s*(?P<bindings>[^}]+?)\s*\}\s*from\s*(?P<quote>['\"])(?P<specifier>[^'\"]+)(?P=quote)\s*;?",
        re.MULTILINE,
    )
    _EXPORT_STAR_FROM_RE = re.compile(
        r"(?:^|(?<=[;}]))\s*export\s*\*\s*from\s*(?P<quote>['\"])(?P<specifier>[^'\"]+)(?P=quote)\s*;?",
        re.MULTILINE,
    )
    _EXPORT_STAR_AS_NAMESPACE_FROM_RE = re.compile(
        r"(?:^|(?<=[;}]))\s*export\s*\*\s*as\s*(?P<name>[A-Za-z_$][\w$]*)\s*from\s*"
        r"(?P<quote>['\"])(?P<specifier>[^'\"]+)(?P=quote)\s*;?",
        re.MULTILINE,
    )
    _EXPORT_LIST_RE = re.compile(r"(?:^|(?<=[;}]))\s*export\s*\{(?P<bindings>[^}]+)\}\s*;?", re.MULTILINE)
    _EXPORT_DEFAULT_NAMED_DECLARATION_RE = re.compile(
        r"(?:^|(?<=[;}]))\s*export\s+default\s+(?P<kind>(?:async\s+)?function|class)\s+"
        r"(?P<name>[A-Za-z_$][\w$]*)",
        re.MULTILINE,
    )
    _EXPORT_DEFAULT_ANONYMOUS_FUNCTION_RE = re.compile(
        r"(?:^|(?<=[;}]))\s*export\s+default\s+(?P<async>async\s+)?function(?=\s*\()",
        re.MULTILINE,
    )
    _EXPORT_DEFAULT_ANONYMOUS_CLASS_RE = re.compile(
        r"(?:^|(?<=[;}]))\s*export\s+default\s+class(?=\s*\{)", re.MULTILINE
    )
    _EXPORT_DEFAULT_RE = re.compile(
        r"(?:^|(?<=[;}]))\s*export\s+default\s+(?P<expression>[^;\n]+);?", re.MULTILINE
    )
    _UNTRANSFORMED_ESM_RE = re.compile(
        r"(?:^|(?<=[;}]))\s*(?P<keyword>import|export)\b", re.MULTILINE
    )
    _IDENTIFIER_RE = re.compile(r"^[A-Za-z_$][\w$]*$")

    def __init__(
        self,
        context: JSContext,
        session: NetworkSession,
        page_url: str,
        origin_policy: OriginPolicy,
    ) -> None:
        self._context = context
        self._session = session
        self._page_url = page_url
        self._origin_policy = origin_policy
        self._registered_modules: set[str] = set()

        self._context.eval(
            """
            globalThis.__phantom_module_exports = Object.create(null);
            globalThis.__phantom_module_factories = Object.create(null);
            globalThis.__phantom_module_execution_stack = [];

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
                globalThis.__phantom_module_execution_stack.push(url);

                try {
                    factory(exports, globalThis.__phantom_require);
                    return exports;
                } catch (error) {
                    delete globalThis.__phantom_module_exports[url];
                    if (error && error.__phantom_module_execution_error) {
                        throw error;
                    }

                    const message = error && typeof error === "object" && "message" in error
                        ? error.message
                        : String(error);
                    const executionError = new Error(
                        "PhantomCurl module execution failed in " + url
                        + " (load chain: "
                        + globalThis.__phantom_module_execution_stack.join(" -> ")
                        + "): " + message
                    );
                    executionError.__phantom_module_execution_error = true;
                    throw executionError;
                } finally {
                    globalThis.__phantom_module_execution_stack.pop();
                }
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

        try:
            self._context.eval(
                "globalThis.__phantom_module_factories["
                f"{json.dumps(module_url)}"
                "] = function (exports, __require) {\n"
                f"{transformed_source}\n"
                "};"
            )
        except JSRuntimeError as error:
            message = f"Failed to compile module {module_url!r}: {error}"
            if syntax_excerpt := self._find_untransformed_esm_syntax(transformed_source):
                message += f"; unsupported ESM syntax near {syntax_excerpt!r}"
            raise InterceptorError(message) from error

        for dependency_url in dependencies:
            if dependency_url not in self._registered_modules:
                self._register_module(dependency_url, self._fetch_module(dependency_url, module_url))

    def _execute_module(self, module_url: str) -> None:
        self._context.eval(f"globalThis.__phantom_require({json.dumps(module_url)});")

    def _transform(self, source: str, module_url: str) -> tuple[str, list[str]]:
        dependencies: list[str] = []
        exports: list[tuple[str, str]] = []
        dependency_references: dict[str, str] = {}
        dependency_declarations: list[str] = []
        dependency_execution_prelude: list[str] = []
        import_prelude: list[str] = []
        module_prelude: list[str] = []
        post_dependency_prelude: list[str] = []

        def require_dependency(dependency_url: str) -> str:
            """Return the per-factory variable holding one dependency's exports.

            Static ESM dependencies execute before the importing module's body.
            The variable is declared before the module's export accessors, then
            assigned after them. A cyclic importer can therefore see a live
            export accessor (and its normal JavaScript TDZ error) instead of a
            permanently copied ``undefined`` value.
            """
            if dependency_url not in dependency_references:
                variable_name = f"__phantom_dependency_{len(dependency_references)}"
                dependency_references[dependency_url] = variable_name
                dependency_declarations.append(f"let {variable_name};")
                dependency_execution_prelude.append(
                    f"{variable_name} = __require({json.dumps(dependency_url)});"
                )
            return dependency_references[dependency_url]

        def add_dependency(specifier: str) -> tuple[str, str]:
            """Resolve a specifier and return its URL plus preloaded reference."""
            dependency_url = self._resolve_url(specifier, module_url)
            if dependency_url not in dependencies:
                dependencies.append(dependency_url)
            return dependency_url, require_dependency(dependency_url)

        def import_from(match: re.Match[str]) -> str:
            _, dependency_reference = add_dependency(match.group("specifier"))
            import_prelude.extend(self._translate_import(match.group("clause"), dependency_reference))
            return ""

        source = self._IMPORT_FROM_RE.sub(import_from, source)

        def import_side_effect(match: re.Match[str]) -> str:
            add_dependency(match.group("specifier"))
            return ""

        source = self._IMPORT_SIDE_EFFECT_RE.sub(import_side_effect, source)

        def export_from(match: re.Match[str]) -> str:
            _, dependency_reference = add_dependency(match.group("specifier"))

            for binding in match.group("bindings").split(","):
                imported_name, exported_name = self._parse_export_binding(binding)
                module_prelude.append(
                    self._property_getter(
                        "exports",
                        exported_name,
                        f"{dependency_reference}[{json.dumps(imported_name)}]",
                    )
                )

            return ""

        source = self._EXPORT_FROM_RE.sub(export_from, source)

        def export_star_as_namespace_from(match: re.Match[str]) -> str:
            _, dependency_reference = add_dependency(match.group("specifier"))
            exported_name = match.group("name")
            module_prelude.append(
                self._property_getter("exports", exported_name, dependency_reference)
            )
            return ""

        source = self._EXPORT_STAR_AS_NAMESPACE_FROM_RE.sub(export_star_as_namespace_from, source)

        def export_star_from(match: re.Match[str]) -> str:
            _, dependency_reference = add_dependency(match.group("specifier"))
            post_dependency_prelude.append(
                f"for (const exportName of Object.keys({dependency_reference})) {{\n"
                '    if (exportName !== "default") {\n'
                "        Object.defineProperty(exports, exportName, {\n"
                "            configurable: true,\n"
                "            enumerable: true,\n"
                "            get: function () {\n"
                f"                return {dependency_reference}[exportName];\n"
                "            },\n"
                "        });\n"
                "    }\n"
                "}"
            )
            return ""

        source = self._EXPORT_STAR_FROM_RE.sub(export_star_from, source)

        def export_default_named_declaration(match: re.Match[str]) -> str:
            name = match.group("name")
            exports.append((name, "default"))
            return f"{match.group('kind')} {name}"

        source = self._EXPORT_DEFAULT_NAMED_DECLARATION_RE.sub(export_default_named_declaration, source)

        def export_default_anonymous_function(match: re.Match[str]) -> str:
            exports.append(("__phantom_default_export", "default"))
            async_prefix = match.group("async") or ""
            return f"const __phantom_default_export = {async_prefix}function"

        source = self._EXPORT_DEFAULT_ANONYMOUS_FUNCTION_RE.sub(export_default_anonymous_function, source)

        def export_default_anonymous_class(match: re.Match[str]) -> str:
            exports.append(("__phantom_default_export", "default"))
            return "const __phantom_default_export = class"

        source = self._EXPORT_DEFAULT_ANONYMOUS_CLASS_RE.sub(export_default_anonymous_class, source)

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

        export_prelude = [
            self._property_getter("exports", export_name, local_name)
            for local_name, export_name in exports
        ]
        module_body = "\n".join(
            [
                *export_prelude,
                *module_prelude,
                *dependency_execution_prelude,
                *post_dependency_prelude,
                source,
            ]
        )
        indented_module_body = "\n".join(
            f"    {line}" if line else "" for line in module_body.splitlines()
        )
        transformed_source = "\n".join(
            [
                *dependency_declarations,
                "const __phantom_imports = Object.create(null);",
                *import_prelude,
                "with (__phantom_imports) {",
                indented_module_body,
                "}",
            ]
        )
        return transformed_source, dependencies

    def _translate_import(self, clause: str, dependency_reference: str) -> list[str]:
        """Create module-local live accessors for one supported import clause."""
        clause = clause.strip()

        if clause.startswith("{") and clause.endswith("}"):
            return self._translate_named_imports(clause, dependency_reference)
        if clause.startswith("* as "):
            namespace = clause.removeprefix("* as ").strip()
            self._require_identifier(namespace, "namespace import")
            return [self._property_getter("__phantom_imports", namespace, dependency_reference)]
        if "," in clause:
            default_name, remainder = clause.split(",", 1)
            self._require_identifier(default_name.strip(), "default import")
            named_import = self._translate_import(remainder.strip(), dependency_reference)
            return [
                self._property_getter(
                    "__phantom_imports", default_name.strip(), f"{dependency_reference}.default"
                ),
                *named_import,
            ]

        self._require_identifier(clause, "default import")
        return [self._property_getter("__phantom_imports", clause, f"{dependency_reference}.default")]

    def _translate_named_imports(self, clause: str, dependency_reference: str) -> list[str]:
        """Create live import accessors for a ``{ name as local }`` clause."""
        bindings: list[str] = []
        for binding in clause[1:-1].split(","):
            original_name, local_name = self._parse_import_binding(binding)
            bindings.append(
                self._property_getter(
                    "__phantom_imports",
                    local_name,
                    f"{dependency_reference}[{json.dumps(original_name)}]",
                )
            )
        return bindings

    @staticmethod
    def _property_getter(target: str, property_name: str, expression: str) -> str:
        """Return JavaScript that exposes ``expression`` as a live accessor."""
        return (
            f"Object.defineProperty({target}, {json.dumps(property_name)}, {{\n"
            "    configurable: true,\n"
            "    enumerable: true,\n"
            "    get: function () {\n"
            f"        return {expression};\n"
            "    },\n"
            "});"
        )

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
        if not self._origin_policy.allows(self._origin(self._page_url), self._origin(module_url)):
            raise InterceptorError(
                f"Module {module_url!r} imported by {importer_url!r} is outside the page's same-origin boundary "
                "unless OriginPolicy allows the target origin"
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
    def _origin(url: str) -> str:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
            raise InterceptorError("Module URLs must resolve to an HTTP or HTTPS origin")
        try:
            port = parsed.port
        except ValueError as error:
            raise InterceptorError("Module URL contains an invalid port") from error

        scheme = parsed.scheme.lower()
        hostname = parsed.hostname.lower()
        host = f"[{hostname}]" if ":" in hostname else hostname
        default_port = 443 if scheme == "https" else 80
        if port in {None, default_port}:
            return f"{scheme}://{host}"
        return f"{scheme}://{host}:{port}"

    @classmethod
    def _find_untransformed_esm_syntax(cls, source: str) -> str | None:
        """Return a short diagnostic excerpt for remaining top-level ESM syntax."""
        match = cls._UNTRANSFORMED_ESM_RE.search(source)
        if match is None:
            return None

        start = match.start("keyword")
        excerpt = source[start : start + 160]
        return " ".join(excerpt.split())

    @classmethod
    def _require_identifier(cls, value: str, description: str) -> None:
        if not cls._IDENTIFIER_RE.fullmatch(value):
            raise InterceptorError(f"Unsupported {description}: {value!r}")
