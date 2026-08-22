# ModuleLoader: повний розбір static ESM у PhantomCurl

> Цей документ описує **фактичний поточний**
> `phantom_curl.bridge.module_loader.ModuleLoader`.
>
> PhantomCurl не є Chromium і не заявляє повну сумісність ESM. Це легкий
> static module loader для підтриманого підмножини синтаксису. Тут зафіксовано
> не лише «що працює», а й чому деякі межі не можна чесно зняти ще одним regex.

## Як читати цей файл

Якщо треба швидко згадати модель — прочитай розділи 1, 3, 6 і 14.
Якщо треба змінювати код — прочитай 5–10 та спершу додай fixture-тест.
Якщо реальний сайт падає — почни з 12, а не з випадкового patch-а.

## 1. Яку проблему вирішує ModuleLoader

Класичний script можна віддати QuickJS майже безпосередньо:

```js
document.body.setAttribute("ready", "yes");
```

Модуль має залежності:

```js
// main.js
import { answer } from "./math.js";
document.body.textContent = String(answer);
```

```js
// math.js
export const answer = 42;
```

Для `main.js` треба:

```text
1. знайти math.js відносно main.js;
2. перевірити origin;
3. скачати source;
4. знайти static import/export;
5. підготувати весь статичний граф;
6. не скачувати URL двічі;
7. виконати залежність до тіла імпортера;
8. передати exports між модулями;
9. показати помилку з URL і load chain.
```

QuickJS у цьому проєкті виконує JavaScript, але його Python binding не дає
callback, через який ми могли б зареєструвати власний loader для native ESM
dependencies. Тому `ModuleLoader` реалізує контрольований static subset сам.

```text
Page
  ├─ будує DOM і встановлює browser-like API
  ├─ знаходить <script type="module">
  └─ передає його ModuleLoader

ModuleLoader
  ├─ знаходить підтримані import/export форми
  ├─ реєструє graph як JavaScript factory
  ├─ виконує entry через внутрішній __phantom_require
  └─ додає URL до діагностики

NetworkSession
  └─ робить HTTP GET для module source

QuickJS
  └─ компілює та виконує підготовлений JavaScript
```

## 2. Терміни

### Module

Файл JavaScript або inline блок з `type="module"`.

```html
<script type="module" src="/assets/main.js"></script>
```

### Entry module

Модуль, який сторінка попросила виконати безпосередньо.

### Dependency

Модуль, який інший модуль імпортує:

```text
main.js -> ui.js -> format.js
```

### Graph

Усі модулі плюс стрілки import. Це не завжди дерево:

```text
             ┌-> price.js
main.js -----┤
             └-> cart.js -----> price.js
```

`price.js` має бути скачаний і виконаний один раз для однієї `Page`.

### Static import

Шлях відомий до запуску:

```js
import { render } from "./render.js";
```

### Dynamic import

Шлях обчислюється вже під час роботи:

```js
const module = await import("./screens/" + screen + ".js");
```

Поточний loader працює лише зі static import. Це інша асинхронна API-модель,
а не дрібний недописаний regex.

### Factory

Підготовлений модуль зберігається так:

```js
function (exports, __require) {
    // transformed source
}
```

Створити factory — **зареєструвати** module. Викликати її — **виконати**.
Це різні фази.

### Exports object

Внутрішній словник модуля:

```js
{ answer: 42, default: "math" }
```

Власні exports і re-export-и створюються accessor-властивостями. Тому
`namespace.value` може бачити актуальне `export let value`. Але `import { value
}` перетворюється на локальний `const` і є snapshot; це важлива межа, а не
деталь формулювання.

## 3. Шлях від module script до QuickJS

Для external script:

```html
<script type="module" src="/assets/main.js"></script>
```

ланцюг такий:

```text
Page
  -> ModuleLoader.execute_external("/assets/main.js")
  -> _resolve_url
  -> _fetch_module
  -> _register_module
  -> _execute_module
  -> __phantom_require(entry URL)
```

Для inline module нема фізичного URL:

```html
<script type="module">
  import { start } from "./app.js";
  start();
</script>
```

`execute_inline()` дає йому внутрішню стабільну адресу:

```text
https://site.test/page#inline-script_3
```

Вона потрібна, щоб:

1. `./app.js` мав коректну URL-базу;
2. cache відрізнив два inline scripts.

Fragment не надсилається в HTTP; це ключ усередині loader-а.

### Чому один loader належить одній Page

Page має власні QuickJS context, DOM, URL і виконані exports. Інша Page не
повинна бачити module cache першої. Саме тому loader створюється у Page, а не
глобально на весь `PhantomClient`.

## 4. `__phantom_require`: маленький runtime

Під час створення loader встановлює в QuickJS:

```js
globalThis.__phantom_module_exports = Object.create(null);
globalThis.__phantom_module_factories = Object.create(null);
globalThis.__phantom_module_execution_stack = [];
```

`Object.create(null)` — чистий словник без успадкованих `toString`,
`constructor` тощо. Це зручніше для URL-ключів, ніж звичайний `{}`.

Скорочена логіка runtime:

```js
globalThis.__phantom_require = function (url) {
    if (Object.prototype.hasOwnProperty.call(__phantom_module_exports, url)) {
        return __phantom_module_exports[url];
    }

    const factory = __phantom_module_factories[url];
    if (!factory) {
        throw new Error("Module was not registered: " + url);
    }

    const exports = Object.create(null);
    __phantom_module_exports[url] = exports;
    __phantom_module_execution_stack.push(url);

    try {
        factory(exports, __phantom_require);
        return exports;
    } finally {
        __phantom_module_execution_stack.pop();
    }
};
```

Рядок за рядком:

1. `hasOwnProperty.call` перевіряє cache. Така форма потрібна, бо чистий
   словник не має свого `hasOwnProperty`.
2. Якщо exports уже існує, модуль не виконується вдруге.
3. Якщо factory немає, це внутрішня помилка реєстрації.
4. `exports` кладеться у cache до виклику factory. Це обриває нескінченний
   цикл `a -> b -> a`.
5. URL кладеться у stack для корисної діагностики.
6. `finally` очищає stack навіть після `throw`.

Реальний runtime має ще `catch`: після помилки видаляє частково виконаний
exports object, додає `load chain`, і не обгортає той самий error багато разів.

Приклад:

```text
PhantomCurl module execution failed in leaf.js
(load chain: entry.js -> feature.js -> leaf.js): value is not initialized
```

## 5. Реєстрація і виконання — різні фази

`_register_module(module_url, source)` робить таке:

```py
if module_url in self._registered_modules:
    return

self._registered_modules.add(module_url)
transformed_source, dependencies = self._transform(source, module_url)
compile_factory_in_quickjs(transformed_source)

for dependency_url in dependencies:
    register_the_dependency()
```

URL потрапляє у `_registered_modules` до рекурсії. Інакше цикл:

```text
register(a) -> register(b) -> register(a) -> ...
```

ніколи не завершився б.

Після реєстрації `_execute_module()` викликає:

```py
self._context.eval(f"globalThis.__phantom_require({json.dumps(module_url)});")
```

`json.dumps()` безпечно робить URL JavaScript string literal, а не вставляє
неекранований текст у generated code.

Є два різні cache:

| Де | Що зберігає | Для чого |
| --- | --- | --- |
| Python `_registered_modules` | URL готової/підготовлюваної factory | не реєструвати та не качати файл двічі |
| JS `__phantom_module_exports` | exports виконуваного/виконаного модуля | не виконувати factory двічі |

## 6. `_transform`: що повертає і з чого складається

Сигнатура:

```py
def _transform(self, source: str, module_url: str) -> tuple[str, list[str]]:
```

Повертає:

```py
transformed_source, dependencies
```

Робочі структури:

| Змінна | Зберігає | Навіщо |
| --- | --- | --- |
| `dependencies` | абсолютні URL | Python рекурсивно їх реєструє |
| `exports` | `(local_name, public_name)` | створити getter для власного export |
| `dependency_references` | URL → `__phantom_dependency_N` | один URL не require-иться двічі у factory |
| `dependency_prelude` | `const dep = __require(url)` | dependencies запускаються до source body |
| `module_prelude` | import `const` та named/namespace re-export getter-и | bindings після dependency execution |
| `post_dependency_prelude` | `export *` loop | перелік ключів лише після `__require` |

### Одна dependency — один reference

Для:

```js
import one from "./math.js";
import { answer } from "./math.js";
```

створюється лише один fetch/require reference:

```js
const __phantom_dependency_0 = __require("https://site.test/math.js");
const one = __phantom_dependency_0.default;
const { answer } = __phantom_dependency_0;
```

`one` і `answer` тут — локальні snapshot-константи. Сам object
`__phantom_dependency_0` при цьому містить accessor exports.

### Порядок transform-ів

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

`export { name as result } from "./x.js"` має обробитися до простого
`export { name as result };`, інакше `from "./x.js"` лишиться в generated JS.

### Точний порядок generated factory

```text
1. створити getter-и для власних exports;
2. виконати direct static dependencies через __require;
3. створити import const і named/namespace re-export getter-и;
4. для export * перелічити вже існуючі dependency exports;
5. виконати source body.
```

Власні export getter-и йдуть першими навмисно. У циклі інший module може
побачити binding object до того, як source завершився. Якщо він прочитає
неініціалізований `const`/`let` через namespace object, JavaScript чесно кине
TDZ error.

## 7. Чому dependency виконується перед body

Source:

```js
globalThis.order.push("entry-body");
import "./dependency.js";
export const result = globalThis.order.join(">");
```

Dependency:

```js
globalThis.order.push("dependency-body");
```

Static ESM import не є звичайним викликом у точці тексту. Очікуваний порядок:

```text
dependency-body -> entry-body
```

Generated code наближено має вигляд:

```js
Object.defineProperty(exports, "result", {
    get: function () { return result; },
});
const __phantom_dependency_0 = __require("https://site.test/dependency.js");
globalThis.order.push("entry-body");
const result = globalThis.order.join(">");
```

Старий loader вставляв `__require` на текстове місце import і помилково давав
`entry-body -> dependency-body`. Regression test захищає правильний варіант.

## 8. Підтримані `import`

Нижче `D` — це `__phantom_dependency_0`.

### Named import

```js
import { answer } from "./math.js";
```

стає:

```js
const { answer } = D;
```

### Alias

```js
import { answer as result } from "./math.js";
```

стає:

```js
const { answer: result } = D;
```

### Default import

```js
import mathName from "./math.js";
```

стає:

```js
const mathName = D.default;
```

### Namespace import

```js
import * as math from "./math.js";
```

стає:

```js
const math = D;
```

`math` посилається на exports object. Тому `math.counter` може бачити оновлене
значення `export let counter`; сам `math` не є копією object-а.

### Default плюс named/namespace

```js
import mathName, { answer as result } from "./math.js";
```

стає двома константами:

```js
const mathName = D.default;
const { answer: result } = D;
```

### Side-effect import

```js
import "./setup.js";
```

Видалиться зі source, але залишить:

```js
const __phantom_dependency_0 = __require("https://site.test/setup.js");
```

Тобто setup.js виконається до body поточного модуля.

### Межа named/default import

У справжньому ESM named/default import — live binding. У поточній легкій
трансформації `const { answer } = D` копіює поточне значення. Для динамічного
читання export, який може змінитися, використовуй namespace import:

```js
import * as math from "./math.js";
console.log(math.answer);
```

Це не пораду для користувачів бібліотеки «переписати сайт». Це технічний опис
межі PhantomCurl, потрібний для правильного діагностування складних bundles.

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

Transformer прибирає `export` і створює getter:

```js
Object.defineProperty(exports, "counter", {
    configurable: true,
    enumerable: true,
    get: function () { return counter; },
});
let counter = 0;
```

Тому namespace consumer, який читає `module.counter`, бачить нове значення
після `counter += 1`.

### Export list

```js
const internal = 42;
export { internal as answer };
```

має getter:

```js
Object.defineProperty(exports, "answer", {
    get: function () { return internal; },
});
const internal = 42;
```

### Default export

```js
export default "math";
```

стає логічно таким:

```js
Object.defineProperty(exports, "default", {
    get: function () { return __phantom_default_export; },
});
const __phantom_default_export = "math";
```

Так само підтримуються named/anonymous default function та class:

```js
export default function greet() { return "hi"; }
export default function () { return "anonymous"; }
export default class Cart {}
export default class { }
```

Anonymous forms отримують тимчасове
`__phantom_default_export`, бо на них інакше нема як послатися у getter-і.

### Named re-export

```js
export { answer as result } from "./math.js";
```

створює forwarding getter:

```js
Object.defineProperty(exports, "result", {
    get: function () {
        return __phantom_dependency_0["answer"];
    },
});
```

### Star re-export

```js
export * from "./values.js";
```

Після запуску values.js loader проходить по його ключах та ставить forwarding
getter для кожного, крім `default`:

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

`export *` виконується після `__require`, інакше `Object.keys(undefined)`
зламав би factory. Це окремий regression test.

### Namespace re-export

```js
export * as values from "./values.js";
```

стає forwarding getter на exports object dependency:

```js
Object.defineProperty(exports, "values", {
    get: function () { return __phantom_dependency_0; },
});
```

## 10. Regex: що вони роблять і чому не заміняють parser

Приклад `_IMPORT_FROM_RE` шукає:

```js
import { answer as result } from "./math.js";
```

Важливі частини шаблонів:

```text
(?:^|(?<=[;}]))  початок рядка або позиція після ; чи }
\s*               нуль або більше whitespace
(?P<specifier>)   named group, який Python дістає за назвою
(?P<quote>['"])   зберегти тип відкривальної лапки
(?P=quote)        вимагати таку ж закривальну лапку
;?                 крапка з комою необов'язкова
```

Межа після `}` потрібна для частини minified коду:

```js
function marker(){}export{marker};
```

Regex не розуміє весь JavaScript: comments, template literals, regex literals,
Unicode identifier-и, scope, нові синтаксичні форми. Тому це свідомо вузький
transformer, а не AST-parser.

Якщо після transform лишився top-level `import` або `export`, QuickJS не
скомпілює factory. `_find_untransformed_esm_syntax()` додасть excerpt:

```text
unsupported ESM syntax near 'export async function* load() { ...'
```

Це підказка для нового мінімального тесту, а не привід вставити regex одразу
під конкретний production bundle.

## 11. URL, мережа й OriginPolicy

`_resolve_url()` використовує `urljoin`:

```text
importer: https://site.test/assets/main.js
./chunk.js  -> https://site.test/assets/chunk.js
../util.js  -> https://site.test/util.js
/app.js     -> https://site.test/app.js
```

Потім `_origin()` нормалізує scheme, hostname та default port:

```text
https://site.test:443 -> https://site.test
http://site.test:80   -> http://site.test
http://site.test:8080 -> http://site.test:8080
```

`OriginPolicy` same-origin за замовчуванням. CDN origin можна дозволити явно.
Це не browser CORS:

- немає preflight;
- `Access-Control-Allow-*` не читається;
- credentials mode не моделюється;
- звичайний Python `client.get()` це правило не обмежує.

`_fetch_module()` робить GET через спільний `NetworkSession`, додає `Referer`
URL importer-а і відхиляє HTTP status `>= 400`.

Module redirects не моделюються як у браузері: запит стоїть із
`allow_redirects=False`.

## 12. Як читати помилки з реального сайту

Спочатку визнач клас:

| Симптом | Що це означає |
| --- | --- |
| `unsupported ESM syntax near ...` | нова форма static import/export |
| `Module ... outside same-origin boundary` | `OriginPolicy`, не regex |
| `HTTP 404/403` | мережа/доступ, не ESM execution |
| `... is not initialized` | TDZ або складний cycle/evaluation order |
| `URL/TextEncoder/MutationObserver is not defined` | Environment/polyfill, не ESM |
| `parentElement` / DOM method error | DOM implementation, не ESM |

Приклад Rozetka:

```text
PhantomCurl module execution failed in chunk-NSDX4FJZ.js
(load chain: main.js -> ... -> chunk-NSDX4FJZ.js): e is not initialized
```

Це означає:

1. URL resolver, origin policy, fetch і compile для попередніх chunks пройшли;
2. помилка виникла в execution конкретного chunk;
3. це не доказ, що треба ще один export regex;
4. найімовірніша межа — складний cycle і відсутні full live bindings.

## 13. Що перевіряють локальні тести

| Сценарій | Контракт |
| --- | --- |
| shared module | named/default/namespace import, один dependency fetch |
| simple cycle | graph не зациклює loader |
| named/star re-export | правильні ключі та default не проходить через star |
| minified import | підтриманий import без пробілів |
| common static forms | default functions/classes, `async function`, namespace re-export |
| dependency order | dependency body раніше за importer body |
| namespace exports | `export let` видно через namespace, named/star re-export |
| namespace TDZ cycle | раннє читання неініціалізованого export дає error |
| unsupported syntax | URL та excerpt у повідомленні |
| execution error | module load chain |
| cross-origin | same-origin default і явний allowlist |

Тести використовують public flow:

```text
local HTTP fixture -> Page -> ModuleLoader -> QuickJS -> DOM attribute -> assert
```

Вони не прив'язуються до приватної назви на кшталт
`__phantom_dependency_0`, тому можна міняти внутрішній код без безглуздого
переписування тестів.

## 14. `e is not initialized`: що зроблено, а що ні

TDZ означає temporal dead zone:

```js
const copy = value;
const value = "ready";
```

Тут JavaScript не повертає `undefined`: binding уже існує, але ще не
ініціалізований, тому кидається `ReferenceError`.

Справжній ESM engine робить:

1. створення bindings усього graph (instantiation);
2. linkage import/export між файлами;
3. evaluation зі strongly connected components;
4. live bindings для named/default imports.

Поточний loader уже:

- створює export getter-и до запуску dependencies;
- запускає direct dependencies до importer body;
- зберігає exports object у cache;
- дає namespace import доступ до getter-ів;
- показує URL і complete load chain.

Але named/default imports досі є `const` snapshot. Через це складний production
cycle може все ще впасти або поводитися інакше за браузер.

### Чому не використано `with` для імітації live named imports

Під час перевірки розглядалася module-local `with`-scope з getter-ами для
імен import. Він проходив короткі fixtures, але на великому реальному module
Rozetka QuickJS падав уже під час compile з внутрішньою помилкою:

```text
InternalError: unconsistent stack size
```

Це гірше за документовану межу: loader не має ламати engine на великому
bundle. Тому цю техніку не залишено в коді. Поточна модель безпечніша та має
явну межу в README і тут.

### Що потрібно для повної фіксації

Не наступний regex. Потрібні або:

1. JavaScript parser + scope analysis + модульний linker, який переписує
   identifier usage без помилок; або
2. native QuickJS module loader із Python callback для URL/module source.

Наявний Python binding має `Context.module()` для одиночного module source,
але не надає потрібного dependency loading callback. Він не може сам
завантажити навіть локальний `import "./file.js"` у поточному контексті.

Отже це справжня архітектурна наступна версія, не маленька недоробка.

## 15. Підтримано й не підтримано

### Підтримано

- inline та external `<script type="module">`;
- static relative URL, same-origin та OriginPolicy allowlist;
- named/default/namespace/side-effect imports;
- `export const`, `let`, `var`, `function`, `async function`, `class`;
- default expression та named/anonymous default function/class;
- export list;
- named/star/namespace re-export;
- dependency-before-body execution;
- accessor exports для namespace access і re-export forwarding;
- базові cycles, load chain і TDZ diagnostics;
- minified підтримані форми.

### Не підтримано

- dynamic `import()`;
- `import.meta`;
- import maps і bare specifiers (`import x from "react"`);
- top-level `await`;
- JSON/CSS/WASM modules;
- import assertions/attributes;
- `export function*` і `export async function*`;
- повний parsing JavaScript;
- named/default live bindings;
- точна ESM evaluation model усіх складних cycles;
- CORS semantics, module redirects, CSP/integrity/MIME rules;
- credentials modes, streaming, module preload.

## 16. Як додавати ESM-фічу без хаосу

1. Визнач клас помилки через таблицю з розділу 12.
2. Виріж мінімальний приклад із production bundle.
3. Додай короткі module fixtures у `tests/conftest.py`.
4. Перевір результат через `Page` і DOM у `tests/test_page.py`.
5. Додай вузьку зміну тільки для цього класу проблем.
6. Запусти:

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\mypy.exe phantom_curl
git diff --check
```

Реальний сайт — хороший діагностичний сигнал, але поганий regression test:
його bundle й доступність змінюються без нашого контролю.

## 17. Карта файлів

```text
phantom_curl/bridge/module_loader.py
  Regex transform, URL resolution, factory registration, module runtime.

phantom_curl/page.py
  Створює ModuleLoader і віддає йому <script type="module">.

phantom_curl/models.py
  OriginPolicy.

phantom_curl/network/session.py
  HTTP transport, який модулі ділять зі сторінкою.

tests/conftest.py
  Local HTTP module fixtures.

tests/test_page.py
  Контракти через public Page API.
```

Швидкий вибір місця для зміни:

```text
Новий import/export синтаксис? -> _IMPORT_*/_EXPORT_* та _transform
URL/origin?                    -> _resolve_url(), _origin(), OriginPolicy
HTTP load?                     -> _fetch_module(), NetworkSession
TDZ/cycle?                     -> runtime architecture, не regex
window/document API?           -> Page або polyfills, не ModuleLoader
```
