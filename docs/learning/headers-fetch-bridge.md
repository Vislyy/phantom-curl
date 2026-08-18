# `Headers` і fetch-міст: детальний розбір

Цей документ пояснює повний шлях запиту з заголовками через runtime
`phantom-curl`. Його мета — щоб ти міг розібрати реалізацію навіть якщо цього
разу не писав її сам.

## 1. Яку проблему розв'язуємо

На справжній вебсторінці код часто виглядає так:

```js
const headers = new Headers();
headers.set("Accept", "application/json");
headers.set("X-Page", "catalog");

fetch("/api/products", { headers });
```

QuickJS не має браузерного класу `Headers`. Крім того, навіть якщо створити
свій JS-клас, Python не може напряму забрати з нього `Map`: між JS і Python
передається лише JSON. Тому рішення складається з двох незалежних частин:

1. JS-поліфіл дає сторінці звичний клас `Headers`.
2. fetch-міст перетворює екземпляр цього класу на простий об'єкт, який можна
   серіалізувати в JSON і передати Python.

Важливе обмеження: це підтримка **заголовків запиту**. Відповідь fetch поки
не має `response.headers`, а `Request`, `AbortController`, CORS і потокові
тіла ще не реалізовані. Окремий string-only `FormData` subset уже існує й
описаний у [розборі FormData](form-data-fetch.md).

## 2. Повний шлях даних

```text
Скрипт сторінки
    │
    │ new Headers({"X-Page": "catalog"})
    ▼
PhantomHeaders (JS-клас, дані у Map)
    │
    │ serializeFetchHeaders(...)
    ▼
Звичайний JS-об'єкт {"x-page": "catalog"}
    │
    │ JSON.stringify(...)
    ▼
Черга __phantom_pending_fetches
    │
    │ Python: json.loads(...)
    ▼
FetchInterceptor
    │
    │ NetworkSession.request(...)
    ▼
HTTP-сервер
    │
    │ відповідь
    ▼
__phantom_complete_fetch(...)
    │
    ▼
Promise.then(...) у JavaScript
```

Найважливіша думка: сам об'єкт `Headers` **ніколи не перетинає межу між
мовами**. Через межу йде лише його проста JSON-версія.

## 3. Де живе код

| Файл | Відповідальність |
| --- | --- |
| `phantom_curl/engine/js_bundle/polyfills.js` | Надає JS-клас `Headers`. |
| `phantom_curl/engine/dom_builder.py` | Кладе цей клас у `window.Headers` нової сторінки. |
| `phantom_curl/page.py` | Створює fetch-чергу, конвертує `Headers` і виконує її. |
| `phantom_curl/bridge/interceptor.py` | Валідує Python-словник і відправляє HTTP-запит. |
| `tests/test_page.py` | Доводить, що `new Headers()` справді доходить до сервера. |

## 4. Чому поліфіл загорнуто в IIFE

У `polyfills.js` код починається так:

```js
(function () {
    // допоміжні функції та class PhantomHeaders
})();
```

Це IIFE — *Immediately Invoked Function Expression*, тобто «функція, яку
одразу викликають».

- Зовнішні дужки перетворюють `function () { ... }` на вираз.
- Останні `()` одразу викликають цей вираз.
- Змінні `normalizeHeaderName`, `normalizeHeaderValue` і клас
  `PhantomHeaders` не стають випадковими глобальними змінними сторінки.
- У глобальний простір ми виносимо тільки потрібний публічний API — `Headers`.

Без IIFE сайт міг би випадково оголосити власну `normalizeHeaderName` і
зламати наш runtime, або наш код міг би зламати сайт.

## 5. Нормалізація назви заголовка

```js
function normalizeHeaderName(name) {
    const normalized = String(name).toLowerCase();
    if (!/^[!#$%&'*+\-.^_|~0-9a-z]+$/.test(normalized)) {
        throw new TypeError("Invalid HTTP header name");
    }
    return normalized;
}
```

Розберемо послідовно.

### `String(name)`

У браузерному API аргументи часто приводяться до рядка. Тому цей код працює:

```js
headers.set("X-Page", 123);
```

Значення ключа врешті є рядком. Ми робимо так само замість того, щоб
вимагати від сайту ідеальні типи.

### `.toLowerCase()`

HTTP-назви регістронезалежні:

```text
Accept == ACCEPT == accept
```

Ми зберігаємо один канонічний варіант — нижній регістр. Завдяки цьому
`headers.set("Accept", "a")`, а потім `headers.get("ACCEPT")` повертає
`"a"`, а не створює два різні ключі.

### Регулярний вираз

```js
/^[!#$%&'*+\-.^_|~0-9a-z]+$/
```

- `^` означає початок рядка.
- `$` означає кінець рядка.
- `[...]` — допустимий набір одного символу.
- `+` — один або більше таких символів.

Отже, весь ключ має складатися лише з безпечних символів HTTP token:
букв, цифр і перелічених розділових знаків. Пробіл, двокрапка, перенос рядка
або порожня назва не проходять перевірку.

### `throw new TypeError(...)`

`throw` негайно зупиняє операцію та створює помилку. Це краще, ніж тихо
прийняти небезпечний заголовок і відправити пошкоджений HTTP-запит.

## 6. Нормалізація значення

```js
function normalizeHeaderValue(value) {
    const normalized = String(value).trim();
    if (/[\r\n]/.test(normalized)) {
        throw new TypeError("Invalid HTTP header value");
    }
    return normalized;
}
```

### `.trim()`

Прибирає пробіли, табуляції та переноси на краях. Наприклад:

```js
headers.set("Content-Type", " text/plain ");
```

зберігається як `"text/plain"`.

### `\r` і `\n`

- `\r` — carriage return, символ повернення каретки;
- `\n` — line feed, перенос рядка.

У звичайному HTTP-запиті кожен заголовок займає один рядок. Якби значення
могло містити перенос, зловмисний код міг би спробувати «вставити» додатковий
заголовок. Це називають *HTTP header injection*. Перевірка не дозволяє такому
значенню пройти до Python чи мережі.

## 7. Внутрішнє сховище класу

```js
class PhantomHeaders {
    constructor(init) {
        this._headers = new Map();
        // ...
    }
}
```

`class` описує шаблон об'єктів. Коли сайт пише `new Headers()`, фактично
створюється екземпляр `PhantomHeaders`.

`this` означає «цей конкретний екземпляр». Поле `this._headers` — внутрішнє
сховище. Префікс `_` не дає технічного захисту в JS; це домовленість для
розробника: «не використовуй це як публічний API».

`Map` обрано замість звичайного `{}` тому що:

- він явно призначений для ключ → значення;
- має надійні `get`, `set`, `has`, `delete`;
- ключі не конфліктують із властивостями типу `toString`;
- порядок вставки передбачуваний.

## 8. Конструктор і різні форми `init`

### Порожній конструктор

```js
if (init === undefined || init === null) {
    return;
}
```

`undefined` означає, що аргумент не передали. `null` тут також трактуємо як
порожні заголовки. `return` завершує конструктор; `Map` уже створений і пустий.

### Копія іншого `Headers`

```js
if (init instanceof PhantomHeaders) {
    for (const entry of init.entries()) {
        this.set(entry[0], entry[1]);
    }
    return;
}
```

`instanceof` питає: «чи створено `init` цим класом?» Якщо так, ми не
прив'язуємося до його внутрішнього `Map`, а створюємо незалежну копію.

`for ... of` проходить по ітератору. Кожен `entry` — масив із двох елементів:

```js
["accept", "application/json"]
```

`entry[0]` — назва, `entry[1]` — значення. `set` повторно нормалізує їх.

### Масив пар або інший ітерабельний об'єкт

```js
if (typeof init[Symbol.iterator] === "function") {
    for (const pair of init) {
        const values = Array.from(pair);
        if (values.length !== 2) {
            throw new TypeError("Headers initializer must contain name-value pairs");
        }
        this.append(values[0], values[1]);
    }
    return;
}
```

Це підтримує природну форму:

```js
new Headers([
    ["Accept", "application/json"],
    ["X-Page", "catalog"],
]);
```

`Symbol.iterator` — стандартний JS-протокол, який каже, що об'єкт можна
обійти через `for ... of`. `Array.from(pair)` перетворює чергову пару на
звичайний масив. Перевірка `length !== 2` не дозволяє випадково передати
`["Accept"]` або `["A", "B", "C"]`.

Тут використовується `append`, не `set`: якщо в ініціалізаторі є дві однакові
назви, їхні значення об'єднуються так само, як при послідовних `append`.

### Звичайний об'єкт

```js
for (const name of Object.keys(init)) {
    this.append(name, init[name]);
}
```

Це підтримує найпоширеніший короткий запис:

```js
new Headers({"X-Page": "catalog"});
```

`Object.keys(init)` повертає лише власні перелічувані ключі, тому ми не
ходимо по властивостях, успадкованих із prototype.

## 9. Основні методи

### `append`

```js
append(name, value) {
    const normalizedName = normalizeHeaderName(name);
    const normalizedValue = normalizeHeaderValue(value);
    const existing = this._headers.get(normalizedName);
    this._headers.set(
        normalizedName,
        existing ? existing + ", " + normalizedValue : normalizedValue,
    );
}
```

`append` додає ще одне значення. Якщо ключа не було — записує значення. Якщо
був — з'єднує старе й нове через `", "`:

```js
headers.append("X-Tag", "one");
headers.append("x-tag", "two");
// get("X-Tag") === "one, two"
```

Тернарний оператор `умова ? коли_так : коли_ні` тут просто скорочує `if`.

### `set`

```js
set(name, value) {
    this._headers.set(normalizeHeaderName(name), normalizeHeaderValue(value));
}
```

`set` не додає, а повністю замінює значення. Це різниця між:

```js
headers.append("Accept", "text/plain");
headers.append("Accept", "application/json");

headers.set("Accept", "application/json");
```

Після `set` залишається лише останній рядок.

### `get`, `has`, `delete`

```js
get(name) {
    const value = this._headers.get(normalizeHeaderName(name));
    return value === undefined ? null : value;
}

has(name) {
    return this._headers.has(normalizeHeaderName(name));
}

delete(name) {
    this._headers.delete(normalizeHeaderName(name));
}
```

- `get` повертає значення або саме `null`, як браузерний API; не `undefined`.
- `has` повертає `true` або `false`.
- `delete` безпечно нічого не робить, якщо ключа не було.

У `get` тернарний оператор перетворює внутрішній `undefined` від `Map` у
зовнішній браузерний контракт `null`.

## 10. Ітерація

Методи `entries`, `keys`, `values`, `forEach` і `[Symbol.iterator]` дозволяють
сайту читати заголовки багатьма стандартними способами.

```js
entries() {
    return this._sortedEntries()[Symbol.iterator]();
}

[Symbol.iterator]() {
    return this.entries();
}
```

`entries()` повертає ітератор пар. Метод із ключем `[Symbol.iterator]`
пояснює JavaScript, що `Headers` можна обійти через:

```js
for (const [name, value] of headers) {
    console.log(name, value);
}
```

`_sortedEntries()` сортує імена перед ітерацією. Це наближає поведінку до
браузерного `Headers`, де обхід має передбачуваний порядок. Спочатку метод
робить `Array.from(this._headers.entries())`, тобто масив пар з `Map`, а потім
`sort(...)` порівнює `left[0]` і `right[0]` — назви.

## 11. Публічний глобальний API

Наприкінці поліфілу:

```js
if (typeof globalThis.Headers === "undefined") {
    globalThis.Headers = PhantomHeaders;
}
```

`globalThis` — стандартне посилання на глобальний об'єкт JS-середовища.
Перевірка `typeof ... === "undefined"` важлива: якщо QuickJS або майбутня
версія середовища вже матиме нативний `Headers`, ми не перезапишемо кращу
реалізацію своїм поліфілом.

У `DOMBuilder.parse_html()` також є:

```js
globalThis.window.Headers = globalThis.Headers;
```

Наш `window` створює Linkedom після завантаження поліфілів. Тому клас уже є на
`globalThis`, але його треба явно покласти на новий `window`, щоб обидва
стандартні записи працювали:

```js
new Headers();
new window.Headers();
```

## 12. Чому не можна передати `Headers` у JSON напряму

Внутрішнє поле класу — `Map`:

```js
this._headers = new Map();
```

Якщо зробити `JSON.stringify(new Headers({"X-Page": "yes"}))`, JSON не
знає, як серіалізувати `Map` у звичайні поля. У кращому разі Python побачить
порожній об'єкт, у гіршому — форму, яка не відповідає очікуванню мосту.

Python не має отримувати JS-клас. Йому достатньо отримати це:

```js
{"x-page": "yes"}
```

Саме тому в fetch-місті є окреме перетворення.

## 13. `serializeFetchHeaders`: вузький адаптер між API і JSON

У `_install_fetch_bridge()` в `page.py` виконується цей JS-код:

```js
function serializeFetchHeaders(headers) {
    if (!(headers instanceof Headers)) {
        return headers;
    }

    const serialized = Object.create(null);
    for (const [name, value] of headers) {
        serialized[name] = value;
    }
    return serialized;
}
```

### Перша перевірка

```js
if (!(headers instanceof Headers)) {
    return headers;
}
```

Старий API уже підтримував звичайний об'єкт:

```js
fetch("/api", {headers: {"X-Page": "yes"}});
```

Його не потрібно ламати або конвертувати. Якщо `headers` не є екземпляром
нашого класу, функція повертає його без змін. Це і є принцип сумісності:
нова можливість не повинна зламати старі правильні виклики.

### `Object.create(null)`

```js
const serialized = Object.create(null);
```

Створює простий об'єкт **без prototype**. Тобто в нього немає вбудованих
властивостей на кшталт `toString` чи `constructor`. Для даних, які скоро
підуть у JSON, це корисно: ми зберігаємо лише явні імена заголовків.

Звичайний `{}` також міг би спрацювати в цьому конкретному коді. Варіант без
prototype просто чіткіше передає намір: це контейнер даних, а не об'єкт із
поведінкою.

### Цикл

```js
for (const [name, value] of headers) {
    serialized[name] = value;
}
```

Завдяки `[Symbol.iterator]()` клас `Headers` віддає пари `name`, `value`.
Деструктуризація `[name, value]` одразу розпаковує масив із двох елементів.

Після циклу, наприклад, маємо:

```js
serialized = {
    "accept": "application/json",
    "x-page": "catalog",
};
```

Тепер це безпечний JSON-об'єкт, усі ключі й значення якого — рядки.

## 14. Де адаптер викликається у `fetch`

```js
const rawHeaders = options.headers === undefined ? {} : options.headers;
const headers = serializeFetchHeaders(rawHeaders);
```

Перший рядок реалізує default value:

- якщо `options.headers` не передали, беремо пустий об'єкт `{}`;
- інакше зберігаємо те, що передав сайт.

Другий рядок перевіряє, чи це `Headers`, і за потреби конвертує. Після нього
змінна `headers` містить або старий plain object, або новий plain object,
створений із `Headers`. Тобто нижня частина мосту не мусить знати про два
типи.

Далі запит кладеться в чергу:

```js
globalThis.__phantom_pending_fetches.push({
    id: id,
    url: input,
    method: method,
    headers: headers,
    body: body,
});
```

`id` зв'язує майбутню HTTP-відповідь із конкретним Promise. `url`, `method`,
`headers` і `body` — це лише дані. Функції, `Map`, DOM-вузли й Promise не
потрапляють у цей об'єкт.

## 15. Як дані доходять до Python

У JS є функція:

```js
globalThis.__phantom_take_fetches = function () {
    const pending = globalThis.__phantom_pending_fetches;
    globalThis.__phantom_pending_fetches = [];
    return JSON.stringify(pending);
};
```

Вона працює як «забрати й очистити чергу»:

1. `pending` тимчасово посилається на старий масив;
2. глобальна черга одразу замінюється на новий порожній масив;
3. старий масив серіалізується й повертається Python.

Так запит не буде виконаний двічі під час наступного циклу runtime.

Python викликає її так:

```python
pending = json.loads(self._context.eval("globalThis.__phantom_take_fetches()"))
```

Розкладемо зсередини назовні:

- `self._context.eval(...)` виконує JS і повертає JSON-рядок;
- `json.loads(...)` перетворює JSON-рядок на Python `list` із `dict`;
- тепер код Python може безпечно перевіряти типи й виконувати HTTP-запит.

## 16. Python-перевірка і запит

`FetchInterceptor._parse_request()` читає поле `headers`:

```python
headers = request.get("headers", {})
if not isinstance(headers, Mapping) or not all(
    isinstance(name, str) and isinstance(value, str) for name, value in headers.items()
):
    raise InterceptorError("fetch headers must be a mapping of strings to strings")
```

- `request.get("headers", {})` бере заголовки, а якщо їх немає — пустий
  словник.
- `Mapping` означає «словникоподібний об'єкт».
- `all(...)` перевіряє **кожну** пару: і ключ, і значення мають бути рядками.
- Якщо хоча б одна пара неправильна, `InterceptorError` не дозволяє надіслати
  неоднозначний або небезпечний запит.

Потім:

```python
request_headers = dict(headers)
request_headers["Referer"] = self._page_url
```

`dict(headers)` створює незалежну копію, щоб не змінювати вхідні дані.
`Referer` визначає сама бібліотека як URL поточної сторінки. Тобто в поточному
мінімальному API код сторінки не контролює цей заголовок.

Після цього `NetworkSession` надсилає вже звичайний HTTP-запит.

## 17. Як HTTP-відповідь повертається в JavaScript

Python передає результат назад викликом:

```python
globalThis.__phantom_complete_fetch(id, result_json)
```

У JS `__phantom_complete_fetch` знаходить `resolve` і `reject` для потрібного
`id`. Якщо Python повернув помилку, викликається `reject(new TypeError(...))`.
Якщо відповідь успішно отримана, створюється спрощений response-об'єкт із:

- `ok`;
- `status`;
- `url`;
- `text()`;
- `json()`.

Після `resolve(...)` QuickJS виконує `.then(...)` як microtask. Метод
`Page._drain_runtime()` повторює обробку queued jobs і fetch-черги, доки не
залишиться негайної роботи. Тому після `page.eval(...)` у тесті результат уже
можна читати з DOM.

## 18. Як читається тест

Ключова частина тесту має такий вигляд:

```js
const requestHeaders = new Headers({"X-Page": "from-headers"});

fetch("/api/echo", {
    method: "POST",
    headers: requestHeaders,
    body: "payload",
})
    .then(response => response.json())
    .then(result => {
        document.body.setAttribute(
            "headers-instance-result",
            JSON.stringify(result),
        );
    });
```

Тест навмисно не передає plain object у `headers`. Він створює справжній
`Headers`, щоб перевірити саме новий адаптер.

Перший `.then(...)` викликає `response.json()`, що повертає Promise з
розібраним тілом відповіді. Другий `.then(...)` записує результат в атрибут
DOM. Це зручний тестовий міст: Python не дістає JS-об'єкт напряму, а читає
рядок через `page.eval(...)` і робить `json.loads(...)`.

Локальний `/api/echo` повертає заголовок `X-Page`. Перевірки:

```python
assert result["header"] == "from-headers"
assert result["body"] == "payload"
```

доводять одразу дві речі: заголовок пройшов у мережу, а тіло запиту не було
загублене під час зміни мосту.

## 19. Чому одна друкарська помилка зламала багато тестів

Під час розробки легко написати:

```js
serializedFetchHeaders(rawHeaders)
```

замість правильної назви:

```js
serializeFetchHeaders(rawHeaders)
```

JS кидає `ReferenceError`, тому Promise fetch відхиляється ще до того, як
запит потрапить у чергу. Через це падають не лише нові тести `Headers`, а й
усі старі тести, які використовують fetch, timers або Element-автодренування.

Це не означає, що «все зламано у багатьох місцях». Часто багато падінь мають
одну спільну першопричину. Шукати варто найкоротше й найконкретніше повідомлення
помилки — у цьому випадку `serializedFetchHeaders is not defined`.

## 20. Чого ця реалізація навмисно не робить

Поточний `Headers` — корисний, але не повний браузерний стандарт.

- Немає `response.headers`.
- Немає guards (`immutable`, `request`, `request-no-cors`, `response`).
- Немає спеціальної семантики `Set-Cookie`.
- Немає класу `Request`.
- `FormData` підтримує лише строкові поля; `Blob`, `File` та HTML-форму в
  конструкторі не підтримано.
- Немає `AbortController`/`AbortSignal` і скасування запиту.
- Немає CORS або preflight-запитів.

Кожен із цих пунктів — окрема фіча зі своїми правилами та тестами. Їх не
варто «підробляти» кількома рядками, бо сайту краще отримати чесну помилку,
ніж тиху неправильну поведінку.

## 21. Що можна самостійно потренувати

Ці вправи не потребують нових можливостей бібліотеки.

1. У тесті заміни `set("Content-Type", " text/plain ")` на `append` двічі
   і передбач результат `get("content-type")`.
2. Додай перевірку, що `headers.get("missing")` повертає `null` у JS і `None`
   у Python.
3. Запусти `Array.from(headers.keys())` і поясни, чому імена в нижньому
   регістрі.
4. Тимчасово передай заголовок із переносом рядка й подивись, на якому етапі
   виникає `TypeError`. Потім поверни тест у чистий стан.
5. Намалюй на папері, де саме `Headers` перестає бути класом і стає простим
   об'єктом. Це ключ до розуміння JS↔Python мостів.

## 22. Як читати наступні навчальні файли

Для `FormData`, `AbortController` та інших великих Web API формат буде такий
самий:

1. проблема й чітка межа фічі;
2. схема руху даних;
3. покроковий розбір важливих фрагментів;
4. пояснення тестів;
5. список свідомо нереалізованих частин;
6. кілька вправ, які можна зробити без переписування всієї фічі.

Тобі не потрібно відразу запам'ятати все. Корисніший спосіб: прочитати
схему, пройти один реальний запит крок за кроком, а потім повернутися до
документа, коли побачиш схожий код у наступній фічі.
