# ModuleLoader: детальний розбір ESM у PhantomCurl

> Це документація до **реального поточного**
> `phantom_curl.bridge.module_loader.ModuleLoader`. Вона описує обмежений,
> контрольований ESM-subset, а не робить вигляд, що PhantomCurl — Chromium.
> Її ціль: щоб через місяць ти міг відкрити один файл, зрозуміти весь шлях
> модуля, побачити межі й знати, де саме правити наступну фічу.

## Зміст

1. [Що вирішує ModuleLoader](#1-що-вирішує-moduleloader)
2. [Терміни](#2-терміни)
3. [Повний шлях виконання](#3-повний-шлях-виконання)
4. [`__phantom_require`: внутрішній runtime](#4-__phantom_require-внутрішній-runtime)
5. [Реєстрація не дорівнює виконанню](#5-реєстрація-не-дорівнює-виконанню)
6. [`_transform`: структура і порядок роботи](#6-_transform-структура-і-порядок-роботи)
7. [Чому залежності йдуть перед тілом модуля](#7-чому-залежності-йдуть-перед-тілом-модуля)
8. [Підтримані `import`](#8-підтримані-import)
9. [Підтримані `export`](#9-підтримані-export)
10. [Regex і їхні межі](#10-regex-і-їхні-межі)
11. [URL, мережа й OriginPolicy](#11-url-мережа-й-originpolicy)
12. [Кеш, цикли та помилки](#12-кеш-цикли-та-помилки)
13. [Що саме тестується](#13-що-саме-тестується)
14. [Що означає `e is not initialized`](#14-що-означає-e-is-not-initialized)
15. [Межі та наступні кроки](#15-межі-та-наступні-кроки)
16. [Карта файлів](#16-карта-файлів)

---

## 1. Що вирішує ModuleLoader

Звичайний script можна віддати QuickJS майже напряму:

```js
document.body.setAttribute("ready", "yes");
```

А модуль залежить від інших файлів:

```js
// main.js
import { answer } from "./math.js";
document.body.textContent = String(answer);
```

```js
// math.js
export const answer = 42;
```

Для `main.js` хтось має:

```text
1. резолвити ./math.js відносно main.js;
2. перевірити, чи дозволений його origin;
3. скачати файл через сесію;
4. знайти його static import/export;
5. підготувати весь статичний граф модулів;
6. не скачати й не виконати той самий URL двічі;
7. передати exports із math.js до main.js;
8. показати нормальну помилку з URL і load chain.
```

QuickJS тут є JavaScript-двигуном, але не готовим browser ESM loader-ом для
HTML-сторінки. `ModuleLoader` — місток між `Page`, мережею та QuickJS.

```text
Page
  ├─ будує DOM та встановлює window/document/fetch/storage
  ├─ знаходить <script type="module">
  └─ передає module script у ModuleLoader

ModuleLoader
  ├─ читає підтримані static import/export через вузькі regex
  ├─ реєструє статичні залежності як factory
  ├─ перетворює ESM на звичайний JavaScript
  └─ виконує entry через __phantom_require

NetworkSession
  └─ робить реальний HTTP GET

QuickJS
  └─ виконує підготовлений JavaScript
```

---

## 2. Терміни

### Module

Файл JavaScript або inline-блок, який має `type="module"`:

```html
<script type="module" src="/assets/main.js"></script>
```

### Entry module

Модуль, який сторінка попросила виконати напряму. У прикладі це `main.js`.

### Dependency

Модуль, який інший модуль імпортує:

```text
main.js -> ui.js -> format.js
```

### Module graph

Усі модулі і стрілки import між ними. Це не завжди дерево, бо один файл може
використовуватися кількома іншими:

```text
             ┌-> price.js
main.js -----┤
             └-> cart.js -----> price.js
```

`price.js` повинен бути підготовлений і виконаний один раз у межах однієї
`Page`.

### Static import

Шлях видно ще до виконання коду:

```js
import { render } from "./render.js";
```

### Dynamic import

Шлях обчислюється вже під час роботи коду:

```js
const screen = await import("./screens/" + name + ".js");
```

Поточний loader підтримує лише static import. Dynamic import потребує іншої
асинхронної Promise-моделі, тому це не «один regex, який забули додати».

### Factory

Перетворений модуль зберігається у вигляді функції:

```js
function (exports, __require) {
    // transformed source
}
```

Створити factory = **зареєструвати** модуль. Викликати factory = **виконати**
модуль. Це дві різні фази.

### Exports object

Це внутрішній словник значень модуля:

```js
{ answer: 42, default: "math" }
```

Його властивості створюються через getter-и. Тому для підтриманих import/export
форм читання `import { value }` бачить актуальне значення `export let value`,
а раннє читання `const`/`let` у циклі дає нормальний TDZ error. Це вже
**live-like binding model**, але все ще не повний browser ESM namespace object:
у нас немає parser-а, повної module instantiation model і всіх правил
специфікації.

---

## 3. Повний шлях виконання

Для external module:

```html
<script type="module" src="/assets/main.js"></script>
```

шлях такий:

```text
Page знаходить script
  |
  v
ModuleLoader.execute_external("/assets/main.js")
  |
  v
_resolve_url -> абсолютний URL + OriginPolicy
  |
  v
_fetch_module -> NetworkSession GET
  |
  v
_register_module -> transform + factory + static dependencies
  |
  v
_execute_module -> __phantom_require(entry URL)
```

Для inline module фізичного URL нема:

```html
<script type="module">
  import { start } from "./app.js";
  start();
</script>
```

Тому `execute_inline()` дає йому штучний стабільний URL, наприклад:

```text
https://site.test/page#inline-script_3
```

Він потрібен, щоб `urljoin` правильно перетворив `./app.js`, а module cache
міг відрізнити один inline script від іншого. Fragment не відправляється в
HTTP-запит: це внутрішній key тільки для loader-а.

### Чому loader належить конкретній Page

Одна `Page` має один QuickJS context, один DOM та одну сторінкову URL-базу.
Інша сторінка не повинна бачити exports або виконаний модуль першої. Тому
`Page._install_module_loader()` створює loader для поточного середовища, а не
глобальний singleton на весь `PhantomClient`.

---

## 4. `__phantom_require`: внутрішній runtime

У `ModuleLoader.__init__()` Python виконує у QuickJS приблизно це:

```js
globalThis.__phantom_module_exports = Object.create(null);
globalThis.__phantom_module_factories = Object.create(null);
globalThis.__phantom_module_execution_stack = [];
```

### Чому `globalThis`

`globalThis` — стандартний глобальний об'єкт JavaScript. Умовно це спільний
для всього JS-контексту Python-словник.

### Чому `Object.create(null)`

Звичайний `{}` має успадковані властивості типу `toString`. `Object.create(null)`
створює чистий словник, що підходить для URL-ключів:

```js
const table = Object.create(null);
```

Runtime має дві таблиці:

```text
__phantom_module_factories
  URL -> function(exports, __require) { ... }

__phantom_module_exports
  URL -> exports уже виконуваного або виконаного модуля
```

Суть `__phantom_require`:

```js
globalThis.__phantom_require = function (url) {
    if (Object.prototype.hasOwnProperty.call(globalThis.__phantom_module_exports, url)) {
        return globalThis.__phantom_module_exports[url];
    }

    const factory = globalThis.__phantom_module_factories[url];
    if (!factory) {
        throw new Error("PhantomCurl module was not registered: " + url);
    }

    const exports = Object.create(null);
    globalThis.__phantom_module_exports[url] = exports;
    globalThis.__phantom_module_execution_stack.push(url);

    try {
        factory(exports, globalThis.__phantom_require);
        return exports;
    } finally {
        globalThis.__phantom_module_execution_stack.pop();
    }
};
```

Рядок за рядком:

1. `hasOwnProperty.call(...)` перевіряє cache. Така форма потрібна, бо чистий
   словник не має свого методу `hasOwnProperty`.
2. Якщо exports вже є, файл не виконується вдруге.
3. Якщо factory нема, це внутрішня помилка: `_register_module()` не підготував
   модуль, який попросили.
4. Новий `exports` кладеться в cache **до** factory. Це не дає циклу
   `a -> b -> a` піти в нескінченну рекурсію.
5. Поточний URL додається до stack, щоб у помилці з'явився шлях викликів.
6. Factory отримує `exports` і сам `__phantom_require` як параметри.
7. `finally` прибирає URL зі stack навіть тоді, коли код зробив `throw`.

У реальному коді `catch` ще:

- видаляє частково створений exports із cache після падіння;
- оформлює одну зрозумілу помилку з URL і `load chain`;
- не обгортає ту саму помилку повторно в кожному батьківському модулі.

Без `finally` перша помилка лишила б stack зламаним, і наступне повідомлення
показало б хибний маршрут. Без `delete` після помилки наступний import міг би
отримати тихий порожній `{}` замість реальної помилки.

---

## 5. Реєстрація не дорівнює виконанню

### `_register_module(module_url, source)`

Псевдокод:

```py
def _register_module(url, source):
    if url already registered:
        return

    mark url as registered
    transformed_source, dependencies = _transform(source, url)
    compile function(exports, __require) { transformed_source }

    for dependency in dependencies:
        fetch dependency source
        _register_module(dependency, dependency_source)
```

`self._registered_modules` — Python `set[str]`. Він відповідає на питання:
«factory цього URL уже готується або вже готова?»

URL додається до set **до** рекурсивної обробки dependencies:

```text
register(a)
  -> register(b)
       -> register(a)  # одразу return, а не нескінченність
```

### `_execute_module(module_url)`

Коли factories entry-модуля й статичного графа зареєстровані, Python запускає:

```py
self._context.eval(f"globalThis.__phantom_require({json.dumps(module_url)});")
```

`json.dumps()` перетворює URL на коректний JavaScript string literal. Це
важливо для лапок, backslash і Unicode: не можна склеювати JS-код з
неекранованого Python-рядка.

Важлива різниця:

| Дані | Де | Що захищають |
| --- | --- | --- |
| `_registered_modules` | Python | повторну реєстрацію/скачування |
| `__phantom_module_exports` | JavaScript | повторне виконання |

Не плутай ці два cache: вони схожі за метою, але працюють у різних фазах.

---

## 6. `_transform`: структура і порядок роботи

Сигнатура:

```py
def _transform(self, source: str, module_url: str) -> tuple[str, list[str]]:
```

Повертає:

```py
transformed_source, dependencies
```

Усередині є вісім головних структур:

| Змінна | Значення | Для чого |
| --- | --- | --- |
| `dependencies` | абсолютні URL | Python далі їх реєструє |
| `exports` | `(local_name, public_name)` | створити live getter для кожного власного export |
| `dependency_references` | URL → `__phantom_dependency_N` | один URL не require-иться двічі в factory |
| `dependency_declarations` | `let __phantom_dependency_N` | дати getter-ам замкнутися над посиланням ще до запуску dependency |
| `dependency_execution_prelude` | `dep = __require(url)` | запустити dependencies після створення власних export getters |
| `import_prelude` | getter-и на `__phantom_imports` | зробити imported identifier-и живими в scope модуля |
| `module_prelude` | named/namespace re-export getter-и | передати known export без snapshot |
| `post_dependency_prelude` | цикл для `export *` | перелічити ключі лише після `__require` dependency |

### `add_dependency()` і `require_dependency()`

Коли regex знаходить `"./math.js"`, helper робить:

```text
./math.js
  -> _resolve_url(...)
  -> https://site.test/assets/math.js
  -> dependencies.append(url), якщо URL новий
  -> dependency_references[url] = __phantom_dependency_0, якщо це перша поява
  -> dependency_declarations.append(let __phantom_dependency_0)
  -> dependency_execution_prelude.append(__phantom_dependency_0 = __require(url))
```

Два imports одного файла:

```js
import one from "./math.js";
import { answer } from "./math.js";
```

отримають один об'єкт залежності та два live getter-и:

```js
let __phantom_dependency_0;
const __phantom_imports = Object.create(null);
Object.defineProperty(__phantom_imports, "one", {
    get: function () { return __phantom_dependency_0.default; },
});
Object.defineProperty(__phantom_imports, "answer", {
    get: function () { return __phantom_dependency_0["answer"]; },
});
```

Зверни увагу: `let __phantom_dependency_0` оголошується до getter-ів, але
отримує exports object лише трохи пізніше. Це навмисно. Getter існує ще до
виконання dependency, а отже цикл може побачити правильну структуру bindings;
якщо він прочитає неініціалізований `const`/`let`, QuickJS кине TDZ error, а не
збереже неправильне `undefined` назавжди.

### Порядок regex-transform-ів

Порядок не випадковий:

```text
1. import ... from
2. import "..."
3. export { ... } from
4. export * as name from
5. export * from
6. named default function/class
7. anonymous default function
8. anonymous default class
9. export declaration
10. export list
11. plain default expression
```

Наприклад, `export { answer as result } from "./math.js"` має бути знайдений
до коротшого `export { answer as result };`. Інакше коротший regex з'їсть
початок, а `from "./math.js"` залишиться невалідним JavaScript-ом.

### Як складається результат

Наприкінці loader склеює код саме в такому порядку:

```py
"\n".join([
    *dependency_declarations,
    "const __phantom_imports = Object.create(null);",
    *import_prelude,
    "with (__phantom_imports) {",
        *export_prelude,
        *module_prelude,
        *dependency_execution_prelude,
        *post_dependency_prelude,
        source,
    "}",
])
```

Отже factory має структуру:

```text
1. оголосити змінні для exports dependencies;
2. створити чистий module-local object для import bindings;
3. додати до нього getter для кожного named/default/namespace import;
4. увійти в module-local `with` scope;
5. створити власні live export getter-и та re-export getter-и;
6. виконати всі direct static dependencies;
7. зробити `export *` після появи exports object dependency;
8. виконати звичайне тіло цього модуля.
```

### Чому тут використано `with`

У звичайному JavaScript не існує «getter-змінної». `Object.defineProperty`
вміє зробити getter для **властивості**, але не для локального `const answer`.
`with (__phantom_imports)` створює module-local scope: коли source пише
`answer`, JavaScript спочатку знаходить getter-властивість `answer` саме в
`__phantom_imports` і повертає актуальне dependency export.

Цей object створюється всередині factory, тому не засмічує `globalThis` і не
перетинається з import-іменем іншого модуля. Це обмежена техніка для нашого
static subset; справжні ESM не реалізуються через `with`, тому ми не називаємо
її повною реалізацією специфікації.

---

## 7. Чому залежності йдуть перед тілом модуля

Візьмемо такий валідний top-level сценарій:

```js
globalThis.order.push("entry-body");
import "./dependency.js";
export const result = globalThis.order.join(">");
```

Залежність робить:

```js
globalThis.order.push("dependency-body");
```

Static import не є звичайним викликом функції в точці тексту. У ESM залежність
має бути виконана перед тілом entry-модуля. Очікуваний порядок:

```text
dependency-body -> entry-body
```

### Старе наближення

Раніше import перетворювався на `__require(...)` прямо у його позиції:

```js
globalThis.order.push("entry-body");
__require("https://site.test/dependency.js");
```

Тоді було неправильно:

```text
entry-body -> dependency-body
```

### Поточне наближення

Тепер transformed factory виглядає так:

```js
let __phantom_dependency_0;
const __phantom_imports = Object.create(null);
with (__phantom_imports) {
    Object.defineProperty(exports, "result", {
        get: function () { return result; },
    });
    __phantom_dependency_0 = __require("https://site.test/dependency.js");

    globalThis.order.push("entry-body");
    const result = globalThis.order.join(">");
}
```

Це принципово правильніше для ациклічних static graphs: setup/side effects у
dependency стаються до виконання імпортера.

Крім порядку, getter для `exports.result` створюється до dependency execution.
Це дає циклічному модулю можливість побачити binding, а не порожній object.
Якщо binding ще не ініціалізували, getter чесно викликає TDZ error. Це вже
покриває корисний клас циклів, але не замінює повну ESM instantiation/evaluation
model. Чому — у [розділі 14](#14-що-означає-e-is-not-initialized).

---

## 8. Підтримані `import`

Нижче `D` означає `__phantom_dependency_0`. Import не створюється через
`const` або destructuring, бо вони скопіювали б значення один раз. Замість
цього loader створює accessor на module-local `__phantom_imports`.

Загальна форма:

```js
Object.defineProperty(__phantom_imports, "localName", {
    configurable: true,
    enumerable: true,
    get: function () {
        return /* актуальне значення з D */;
    },
});
```

Потім source виконується всередині `with (__phantom_imports)`. Тому кожне
читання `localName` викликає getter знову, а не бере стару копію.

### Named import

```js
import { answer } from "./math.js";
```

стає accessor-ом:

```js
Object.defineProperty(__phantom_imports, "answer", {
    get: function () { return D["answer"]; },
});
```

### Alias

```js
import { answer as result } from "./math.js";
```

стає:

```js
Object.defineProperty(__phantom_imports, "result", {
    get: function () { return D["answer"]; },
});
```

Зліва — ключ у exports залежності, справа — локальна назва.

### Default import

```js
import mathName from "./math.js";
```

стає:

```js
Object.defineProperty(__phantom_imports, "mathName", {
    get: function () { return D.default; },
});
```

### Namespace import

```js
import * as math from "./math.js";
```

стає:

```js
Object.defineProperty(__phantom_imports, "math", {
    get: function () { return D; },
});
```

### Default + named або namespace

```js
import mathName, { answer as result } from "./math.js";
```

стає двома getter-ами:

```js
Object.defineProperty(__phantom_imports, "mathName", {
    get: function () { return D.default; },
});
Object.defineProperty(__phantom_imports, "result", {
    get: function () { return D["answer"]; },
});
```

### Side-effect import

```js
import "./setup.js";
```

Не створює локального accessor-а. Але loader усе одно створює reference і
потім виконує dependency до source body:

```js
let __phantom_dependency_0;
// ... export accessors, якщо вони є ...
__phantom_dependency_0 = __require("https://site.test/setup.js");
```

Це запускає setup.js і дає йому cache key.

`_parse_import_binding()` перевіряє generated identifier-и через
`_IDENTIFIER_RE`. Це не повна Unicode-граматика JS, зате transformer не
вставляє довільний неперевірений текст у generated code.

---

## 9. Підтримані `export`

### Declaration exports

Підтримуються:

```js
export const answer = 42;
export let counter = 0;
export var legacy = true;
export function greet() { return "hi"; }
export async function load() { return "later"; }
export class Cart {}
```

Transformer прибирає `export`, зберігає declaration і до виконання залежностей
створює getter:

```js
Object.defineProperty(exports, "answer", {
    configurable: true,
    enumerable: true,
    get: function () { return answer; },
});
```

Коли source пізніше зробить `let counter = 0` або `counter += 1`, наступне
читання `dependency.counter` викликає getter і бачить нове значення. `async`
не загублюється: `async function load` лишається async function.

### Export list

```js
const internal = 42;
export { internal as answer };
```

перетворюється на:

```js
// getter створюється першим усередині with-scope:
Object.defineProperty(exports, "answer", {
    get: function () { return internal; },
});
const internal = 42;
```

### Default expression

```js
export default "math";
```

перетворюється на:

```js
Object.defineProperty(exports, "default", {
    get: function () { return __phantom_default_export; },
});
const __phantom_default_export = "math";
```

### Named default function/class

```js
export default function greet(name) { return "hi " + name; }
export default class Cart {}
```

стають:

```js
Object.defineProperty(exports, "default", {
    get: function () { return greet; },
});
function greet(name) { return "hi " + name; }
```

Для `export default class Cart {}` getter аналогічно повертає `Cart`.

Назва вже існує у scope, тому її можна експортувати напряму.

### Anonymous default function/class

```js
export default function () { return "anonymous"; }
```

стає:

```js
Object.defineProperty(exports, "default", {
    get: function () { return __phantom_default_export; },
});
const __phantom_default_export = function () { return "anonymous"; };
```

Аналогічно для:

```js
export default class { constructor() { this.value = 1; } }
```

Без тимчасової константи немає імені, яке можна присвоїти у `exports.default`.

### Named re-export

```js
export { answer as result } from "./math.js";
```

породжує:

```js
Object.defineProperty(exports, "result", {
    get: function () {
        return __phantom_dependency_0["answer"];
    },
});
```

Getter не копіює `answer`: якщо source export змінюється пізніше, `result`
бачить це нове значення.

### Star re-export

```js
export * from "./values.js";
```

породжує цикл по ключах:

```js
for (const exportName of Object.keys(__phantom_dependency_0)) {
    if (exportName !== "default") {
        Object.defineProperty(exports, exportName, {
            get: function () {
                return __phantom_dependency_0[exportName];
            },
        });
    }
}
```

`default` свідомо не перевидається — це базове правило ESM. Якщо два
`export *` дають одне ім'я, поточне легке наближення використовує останнє
присвоєння; повна специфікація складніша.

### Namespace re-export

```js
export * as values from "./values.js";
```

стає:

```js
Object.defineProperty(exports, "values", {
    get: function () { return __phantom_dependency_0; },
});
```

Тоді інший модуль може зробити:

```js
import { values } from "./bridge.js";
console.log(values.first);
```

---

## 10. Regex і їхні межі

У loader-і кожна підтримана форма — окремий `re.compile(...)`. Умовно:

```text
_IMPORT_FROM_RE
_IMPORT_SIDE_EFFECT_RE
_EXPORT_FROM_RE
_EXPORT_STAR_AS_NAMESPACE_FROM_RE
_EXPORT_STAR_FROM_RE
...
```

Важливі частини regex:

```text
(?:^|(?<=[;}]))
  початок рядка або позиція після ; чи }.
  Це допомагає з частиною minified коду:
  function f(){}import { x } from "./x.js";

\s*
  нуль або більше whitespace.

(?P<specifier>...)
  named group, який Python дістає як match.group("specifier").

(?P<quote>['"])
  запам'ятати початкову лапку.

(?P=quote)
  закривати рівно такою ж лапкою.

;?
  крапка з комою необов'язкова.
```

### Чому це не parser

JavaScript має comments, template literals, regex literals, вкладені scope,
Unicode identifier-и та багато форм сучасного синтаксису. Regex не будує AST і
не може коректно вирішити всі двозначності JavaScript.

Тому цей код — свідомо вузький transformer для контрольованого static subset.
Він уже дає live-like accessor-и для підтриманих identifier imports/exports,
але коли задача вимагатиме full parsing, усіх scope-правил або повної ESM
instantiation model, правильний шлях — parser чи нативний module runtime, а не
ще двадцять складних regex.

### Діагностика залишеного ESM

Якщо QuickJS не зміг скомпілювати factory, `_find_untransformed_esm_syntax()`
шукає top-level `import`/`export` і додає короткий фрагмент:

```text
unsupported ESM syntax near 'export async function* load() { ...'
```

Це не ідеальний parser error, але дає головне: яку форму треба відтворити
локальним fixture-тестом перед будь-яким patch-ем.

---

## 11. URL, мережа й OriginPolicy

`_resolve_url()` використовує `urljoin`, а не ручне склеювання рядків:

```text
importer: https://site.test/assets/main.js

./chunk.js  -> https://site.test/assets/chunk.js
../utils.js -> https://site.test/utils.js
/app.js     -> https://site.test/app.js
```

Потім `_origin()` нормалізує scheme + host + ефективний port:

```text
https://site.test:443 -> https://site.test
http://site.test:80   -> http://site.test
http://site.test:8080 -> http://site.test:8080
```

Після цього `OriginPolicy` перевіряє target:

```py
policy.allows(page_origin, module_origin)
```

За замовчуванням module scripts same-origin. CDN можна дозволити явно через
`OriginPolicy`. Це policy PhantomCurl, а **не** browser CORS:

- немає preflight;
- `Access-Control-Allow-*` не читається;
- credentials modes не моделюються;
- звичайний Python `client.get()` ця логіка не обмежує.

`_fetch_module()` робить GET через той самий `NetworkSession`, що й сторінка,
та надсилає `Referer` importer-а. HTTP status `>= 400` дає `InterceptorError`
з URL модуля та importer-а.

Поточна межа: модульні redirects не поводяться як у браузері, бо fetch стоїть
з `allow_redirects=False`.

---

## 12. Кеш, цикли та помилки

### Простий цикл

```js
// a.js
import "./b.js";
export const a = "a";

// b.js
import "./a.js";
export const b = "b";
```

Коли b просить a вдруге, `__phantom_module_exports[a]` уже існує. Runtime
повертає цей об'єкт замість повторного запуску a. Тому рекурсія зупиняється.

Це працює, якщо модулі не читають незавершені значення одне одного.

### Load chain

Якщо entry → feature → leaf і код у leaf падає, runtime додає:

```text
PhantomCurl module execution failed in leaf.js
(load chain: entry.js -> feature.js -> leaf.js): ...
```

Помилку не можна загортати ще раз на кожному рівні, інакше користувач побачить
шум на кшталт `entry failed: feature failed: leaf failed`. Для цього існує
технічний marker `__phantom_module_execution_error`.

---

## 13. Що саме тестується

Тести розділені так:

```text
tests/conftest.py
  Локальний HTTP server і короткі JS module fixtures.

tests/test_page.py
  Сценарії через публічний Page API і видимий DOM-результат.
```

Ми не тестуємо `_transform()` лише рядком у вакуумі. Перевіряється повний
контракт:

```text
HTTP fixture -> Page -> ModuleLoader -> QuickJS -> DOM attribute -> assert
```

| Сценарій | Контракт |
| --- | --- |
| shared math module | named/default/namespace import, shared dependency fetch один раз |
| simple cycle | циклічний graph не зациклює loader |
| named/star re-export | правильні exports та виключення default зі star |
| minified import | `import{marker}from"..."` не губиться |
| common static semantics | default function/class, anonymous default forms, `async function`, namespace re-export, порядок dependency-before-body |
| live binding and safe cycle | `export let` видно після зміни і через named/star re-export; deferred read із циклу бачить готовий export |
| TDZ cycle | раннє читання циклічного `const`/`let` кидає error, а не дає тихе `undefined` |
| unsupported syntax | URL і ESM excerpt присутні в error |
| execution error | є module load chain |
| cross-origin modules | same-origin default і явний OriginPolicy allowlist |

### Найкорисніший regression test

`test_page_handles_common_static_module_export_forms_and_dependency_order`
навмисно ставить statement **перед** static import у тексті entry-module. Він
вимагає результат:

```text
dependency-body>entry-body
```

Якби хтось повернув `__require` у текстову позицію import-а, цей тест упав би
з `entry-body>dependency-body`. Тобто він реально захищає ESM-семантику, а не
перевіряє внутрішню змінну заради відсотка coverage.

---

## 14. Що означає `e is not initialized`

На великому bundle помилка на кшталт:

```text
ReferenceError: e is not initialized
```

зазвичай не означає «ще не підтримали один запис `export`». Це TDZ — temporal
dead zone. Мінімальний приклад:

```js
const copy = value;
const value = "ready";
```

JavaScript не повертає `undefined`: binding `value` існує, але його ще не
ініціалізували, тому він кидає `ReferenceError`.

### Чому це пов'язано з ESM

Справжній ESM engine робить більше, ніж `require`:

1. створює bindings для всього графа (instantiation);
2. зв'язує imports з exports (linking);
3. виконує graph із правилами для strongly connected components;
4. підтримує **live bindings**: imported value не просто копія на момент import.

Поточний loader більше не робить named import через snapshot:

```js
const { value } = __phantom_dependency_0;
```

Замість цього він створює module-local accessor:

```js
Object.defineProperty(__phantom_imports, "value", {
    get: function () {
        return __phantom_dependency_0["value"];
    },
});
```

і виконує transformed source у `with (__phantom_imports)`. Коли source читає
`value`, getter читає актуальне export значення саме тоді. Так само власний
`export let value` стає getter-ом на `exports`.

### Що вже покращено

Dependencies запускаються до тіла імпортера. Власні export getter-и
створюються ще до запуску dependencies. Разом це виправляє порядок для
ациклічних graphs, side-effect imports, зміни `export let` після import і
частину корисних циклів із відкладеним читанням.

Наприклад:

```js
// source.js
export let value = "before";
export function setValue(next) { value = next; }

// consumer.js
import { value, setValue } from "./source.js";
setValue("after");
console.log(value); // "after" у підтриманій моделі PhantomCurl
```

А в циклі:

```js
// a.js
import { readA } from "./b.js";
export const a = "ready";
export const result = readA();

// b.js
import { a } from "./a.js";
export function readA() { return a; }
```

`readA()` викликається лише після `a = "ready"`, тому getter повертає
`"ready"`. Це перевіряє локальний regression test.

### Чого це чесно не виправляє

Якщо в циклі dependency реально прочитає `a` **до** рядка
`const a = "ready"`, getter викликає справжню TDZ-помилку `a is not initialized`.
Це правильніше за старе тихе `undefined`: проблема не маскується, а load chain
показує, який module graph її створив.

Проте повної специфікації все ще немає. Справжній ESM engine окремо будує
dependency graph, виконує весь алгоритм instantiation/evaluation і має всі
лексичні/scope-правила. Наш `with`-based local scope покриває підтримані static
форми, але не є заміною parser-а та engine-level module loader-а. Тому error у
великому bundle тепер точніше локалізований, але сам по собі не обіцяє, що
кожен складний production cycle стане сумісним.

---

## 15. Межі та наступні кроки

### Підтримано зараз

- inline та external `<script type="module">`;
- static relative URLs, same-origin і OriginPolicy allowlist;
- named/default/namespace/side-effect imports;
- мінімізовані підтримані static форми;
- `export const`, `let`, `var`, `function`, `async function`, `class`;
- export list, default expression, named/anonymous default function/class;
- named/star/namespace re-export;
- dependency execution після власних export getter-ів;
- live-like accessor-и для підтриманих named/default/namespace imports і exports;
- зміна `export let` після import, deferred reads у частині циклів і TDZ diagnostics;
- registration/execution cache, базові цикли, load-chain diagnostics.

### Не підтримано поки що

- dynamic `import()`;
- `import.meta`;
- import maps і bare specifiers (`import x from "react"`);
- top-level `await`;
- JSON/CSS/WASM modules;
- import attributes/assertions;
- `export function*` та `export async function*`;
- повний JavaScript parsing;
- повна ESM instantiation/evaluation model і точна поведінка всіх складних циклів;
- повна strict-mode/module-scope семантика поза підтриманим accessor subset;
- browser CORS semantics, module redirects, CSP/integrity/MIME rules;
- browser module credentials і streaming/preload.

### Правильний процес для нової фічі

1. Класифікуй помилку: syntax, URL/policy, мережа, DOM/polyfill чи cycle.
2. Виріж із реального сайту мінімальний приклад у `tests/conftest.py`.
3. Напиши тест на DOM/API результат у `tests/test_page.py`.
4. Лише після цього додай вузький transform або іншу архітектурну зміну.
5. Прожени повний набір:

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\mypy.exe phantom_curl
git diff --check
```

Реальний сайт — хороший діагностичний сигнал, але поганий основний regression
test: його bundle, доступність і сторонні ресурси можуть змінитися завтра.

---

## 16. Карта файлів

```text
phantom_curl/bridge/module_loader.py
  Transform, URL resolution, factory registration і __phantom_require runtime.

phantom_curl/page.py
  Створює ModuleLoader і передає йому <script type="module">.

phantom_curl/models.py
  OriginPolicy.

phantom_curl/network/session.py
  Спільний HTTP транспорт.

tests/conftest.py
  Local HTTP fixtures для коротких module graphs.

tests/test_page.py
  Публічні сценарії Page і перевірка DOM-результату.
```

Швидка навігація за типом проблеми:

```text
Новий import/export синтаксис?  -> module_loader.py, _IMPORT_*/_EXPORT_*, _transform
Проблема URL/origin?            -> _resolve_url(), _origin(), OriginPolicy
HTTP module load?               -> _fetch_module(), NetworkSession
TDZ / cycle / порядок?          -> __phantom_require і модель виконання
window/document API?            -> Page/polyfills, не ModuleLoader
```

Ця карта не замінює читання коду, але допомагає не правити перший-ліпший файл
і не змішувати ESM, DOM, мережу та policy в одну «магічну» проблему.
