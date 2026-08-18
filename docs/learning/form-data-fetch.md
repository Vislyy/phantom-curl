# `FormData` і multipart fetch: докладний розбір

Цей документ розбирає реалізацію string-only `FormData` у `phantom-curl`.
Його мета — щоб ти міг пройти весь шлях даних і зрозуміти код, навіть якщо
цього разу рутинну частину реалізував агент.

## 1. Межа фічі

Працює такий код:

```js
const data = new FormData();
data.append("name", "Ada");
data.append("tag", "python");
data.append("tag", "runtime");

fetch("/api/profile", {method: "POST", body: data});
```

Підтримано:

- `append`, `set`, `get`, `getAll`, `has`, `delete`;
- дублікати назв та порядок полів;
- `entries`, `keys`, `values`, `forEach`, `for...of`;
- автоматичне перетворення у `multipart/form-data` в `fetch`.

Навмисно не підтримано:

- `Blob` і `File`;
- файли з `<input type="file">`;
- `new FormData(htmlFormElement)`;
- потоки та великі двійкові body;
- `AbortController`.

Це не неповна реалізація «на один if». Для файлів знадобляться byte buffers,
MIME-типи, filename, кодування, межі пам'яті й нові містки Python↔JS. Тому
поточна фіча чесно обмежена рядковими полями.

## 2. Чому FormData не те саме, що JSON або URLSearchParams

| API | Типовий `Content-Type` | Приклад body |
| --- | --- | --- |
| JSON | `application/json` | `{"name":"Ada"}` |
| URLSearchParams | `application/x-www-form-urlencoded` | `name=Ada&tag=python` |
| FormData | `multipart/form-data; boundary=...` | кілька незалежних частин із заголовками |

`multipart/form-data` — формат, який зазвичай очікують серверні HTML-форми.
Він дозволяє кілька значень одного поля, а в майбутньому — файли. Саме тому
`FormData` не можна правильно передати як простий JSON-об'єкт.

## 3. Схема руху даних

```text
JS сторінки
    │ data.append("name", "Ada")
    ▼
PhantomFormData._entries
    │ [["name", "Ada"], ["tag", "python"]]
    ▼
fetch(..., {body: formData})
    ▼
serializeFormData(...)
    │ ├─ генерує boundary
    │ ├─ збирає multipart body
    │ └─ додає Content-Type, якщо його не встановив сайт
    ▼
JSON-запис у fetch-черзі
    ▼
Python FetchInterceptor
    ▼
NetworkSession → HTTP-сервер
```

Ключова ідея: Python не отримує JS-об'єкт `FormData`. До моменту JSON-містка
він уже став звичайним рядком body та словником заголовків.

## 4. Чому внутрішнє сховище — масив, а не Map

У `polyfills.js` клас починається так:

```js
class PhantomFormData {
    constructor(form) {
        if (form !== undefined) {
            throw new TypeError("PhantomCurl FormData does not support HTML form initialization");
        }
        this._entries = [];
    }
}
```

`Map` не підходить для FormData. У Map може бути лише одне значення на ключ:

```js
new Map([
    ["tag", "python"],
    ["tag", "runtime"],
]);
// ключ "tag" зберігає лише останнє значення
```

А FormData зобов'язаний зберігати дублікати. Тому `_entries` має форму:

```js
[
    ["tag", "python"],
    ["tag", "runtime"],
    ["page", "2"],
]
```

Кожна вкладена пара — `[name, value]`. Порядок масиву дорівнює порядку
додавання, і це важлива частина контракту FormData.

### Чому конструктор відкидає аргумент `form`

У браузері `new FormData(formElement)` обходить усі form controls: disabled
поля, checkbox, select, файли тощо. Наш Linkedom runtime не моделює повний
submit алгоритм і не має `File`. Якщо тихо проігнорувати `form`, сайт відправить
порожній запит і не помітить помилку. Чесний `TypeError` безпечніший.

## 5. `append`: завжди додати нове поле

```js
append(name, value) {
    this._entries.push([String(name), String(value)]);
}
```

- `String(name)` приводить назву до рядка.
- `String(value)` робить те саме зі значенням: число `2` стає `"2"`.
- `push(...)` додає пару в кінець, не перевіряючи дублікати.

Тому:

```js
data.append("tag", "python");
data.append("tag", "runtime");
data.getAll("tag"); // ["python", "runtime"]
```

`append` — це «додай ще одне», а не «онови існуюче».

## 6. Читання й видалення полів

### `get`

```js
get(name) {
    const targetName = String(name);
    for (const entry of this._entries) {
        if (entry[0] === targetName) {
            return entry[1];
        }
    }
    return null;
}
```

`for ... of` обходить масив у порядку. `entry[0]` — name, `entry[1]` — value.
Тому `get` повертає **перше** значення з потрібною назвою. Якщо поля немає,
повертається `null`, а не Python-подібне `None` чи JS `undefined`.

### `getAll`

```js
getAll(name) {
    const targetName = String(name);
    return this._entries
        .filter(entry => entry[0] === targetName)
        .map(entry => entry[1]);
}
```

`filter` залишає всі пари з назвою `targetName`. `map` бере з кожної лише
значення. Результат — новий масив, тому код сторінки не отримує прямого
посилання на наш внутрішній `_entries`.

### `has`

```js
has(name) {
    const targetName = String(name);
    return this._entries.some(entry => entry[0] === targetName);
}
```

`some` повертає `true`, щойно знаходить першу відповідну пару. Це прямий
спосіб відповісти на питання «чи є поле?», без створення проміжного масиву.

### `delete`

```js
delete(name) {
    const targetName = String(name);
    this._entries = this._entries.filter(entry => entry[0] !== targetName);
}
```

`delete` прибирає **всі** пари з даною назвою. `filter` створює новий масив,
а присвоєння замінює старий. Це не видаляє лише перше значення.

## 7. `set`: замінити всі дублікати одним значенням

```js
set(name, value) {
    const targetName = String(name);
    const stringValue = String(value);
    let replaced = false;
    const entries = [];

    for (const entry of this._entries) {
        if (entry[0] !== targetName) {
            entries.push(entry);
        } else if (!replaced) {
            entries.push([targetName, stringValue]);
            replaced = true;
        }
    }

    if (!replaced) {
        entries.push([targetName, stringValue]);
    }
    this._entries = entries;
}
```

`replaced` — булевий прапорець. Алгоритм іде так:

1. Незв'язані поля копіюємо без змін.
2. Перший збіг замінюємо новою парою.
3. Наступні збіги пропускаємо, бо нове значення вже записали.
4. Якщо збігу не було, додаємо поле в кінець.

Це відрізняє `set` від `append`. Після:

```js
data.append("tag", "python");
data.append("tag", "browser");
data.set("tag", "runtime");
```

залишається лише `[["tag", "runtime"]]`.

## 8. Ітератори й forEach

```js
entries() {
    return this._entries.map(entry => [entry[0], entry[1]])[Symbol.iterator]();
}

[Symbol.iterator]() {
    return this.entries();
}
```

`entries` створює копії пар і повертає їхній ітератор. `[Symbol.iterator]`
робить можливим звичайний синтаксис:

```js
for (const [name, value] of data) {
    console.log(name, value);
}
```

`keys` і `values` працюють так само, але повертають лише один елемент пари.
`forEach(callback, thisArg)` перевіряє, що callback справді є функцією, і
викликає її як `callback(value, name, formData)`.

## 9. Як FormData стає глобальним API

Наприкінці поліфілу:

```js
if (typeof globalThis.FormData === "undefined") {
    globalThis.FormData = PhantomFormData;
}
```

`globalThis` — глобальний об'єкт QuickJS. Перевірка не дозволяє замінити
майбутню нативну реалізацію власним поліфілом.

У `DOMBuilder.parse_html()` є ще рядок:

```js
globalThis.window.FormData = globalThis.FormData;
```

Linkedom створює новий `window` уже після завантаження поліфілів. Тому клас
потрібно явно покласти на `window`, інакше `new FormData()` працював би, а
`new window.FormData()` — ні.

## 10. Як fetch розпізнає FormData

У fetch-місті:

```js
const rawBody = options.body === undefined ? null : options.body;
const serializedFormData = rawBody instanceof FormData
    ? serializeFormData(rawBody, headers)
    : null;
```

Перший рядок встановлює default: якщо `body` не передали, беремо `null`.
`instanceof FormData` перевіряє, чи створений body нашим класом. Тернарний
оператор має форму:

```text
умова ? результат_якщо_так : результат_якщо_ні
```

Для FormData викликається `serializeFormData`. Для звичайного рядка
залишається `null`, отже старий fetch-контракт не змінюється.

Потім:

```js
const body = serializedFormData === null ? rawBody : serializedFormData.body;
const requestHeaders = serializedFormData === null ? headers : serializedFormData.headers;
```

Нижня частина fetch завжди отримує рядок body й простий об'єкт headers. Вона
не повинна знати, чи початково сайт передав string, чи FormData.

## 11. `hasFetchHeader`: назви HTTP-заголовків не мають регістру

```js
function hasFetchHeader(headers, name) {
    const targetName = String(name).toLowerCase();
    return Object.keys(headers).some(function (headerName) {
        return headerName.toLowerCase() === targetName;
    });
}
```

Сайт може передати `Content-Type` або `content-type`; це той самий HTTP
заголовок. `Object.keys` дає назви властивостей, а `some` завершується при
першому збігу. Так ми не додаємо автоматичний multipart-заголовок поверх
явно заданого користувачем.

## 12. Boundary: розділювач multipart частин

```js
const boundary = "----PhantomCurlFormBoundary" + Math.random().toString(16).slice(2);
```

`boundary` — випадковий рядок, який розділяє поля тіла. Приклад:

```text
----PhantomCurlFormBoundarya4f69c2
```

- фіксований префікс допомагає дебажити;
- `Math.random()` дає різне число;
- `toString(16)` робить із нього шістнадцятковий текст;
- `slice(2)` прибирає початкове `0.`.

Той самий boundary обов'язково йде в body та в `Content-Type`, інакше сервер
не знатиме, де закінчується поле.

## 13. Як будується multipart body

Для кожної `[name, value]` пари код додає шматок:

```js
chunks.push(
    "--" + boundary + "\r\n"
    + "Content-Disposition: form-data; name=\"" + escapeFormDataName(name) + "\"\r\n\r\n"
    + value + "\r\n"
);
```

Для поля `name=Ada` це означає:

```text
--BOUNDARY\r\n
Content-Disposition: form-data; name="name"\r\n
\r\n
Ada\r\n
```

`\r\n` — CRLF, стандартний HTTP/MIME перенос. Будова однієї частини:

1. `--BOUNDARY` — початок;
2. `Content-Disposition` — службовий заголовок частини;
3. порожній рядок — кінець заголовків частини;
4. значення поля;
5. CRLF перед наступною частиною.

Після всіх полів додається:

```js
chunks.push("--" + boundary + "--\r\n");
```

Два додаткові дефіси після boundary означають остаточне завершення всього
multipart body. `chunks.join("")` з'єднує всі частини в один рядок.

## 14. Захист назви поля в Content-Disposition

```js
function escapeFormDataName(name) {
    return String(name)
        .replace(/\r/g, "%0D")
        .replace(/\n/g, "%0A")
        .replace(/"/g, "%22");
}
```

Name опиняється всередині лапок у рядку `Content-Disposition`. Перенос рядка
або лапка могли б зламати формат. Ми замінюємо ці символи на percent-like
послідовності. Це не повна реалізація WHATWG-правил, але вона не дає полю
вирватися з заголовка частини.

## 15. Найпідступніше місце: екранування Python → JavaScript

JS fetch-міст записаний усередині Python-потрійного рядка. Тому в
`page.py` видно `\\r` і `\\n`, хоча JavaScript має отримати `\r` і `\n`.

```text
Код у page.py      →     рядок після Python      →      JavaScript
"\\r"                     "\r"                         carriage return
```

Якщо в Python-джерелі написати лише `\r`, Python вставить справжній перенос
ще до запуску QuickJS. Усередині JS-regexp це призводить до:

```text
SyntaxError: unexpected line terminator in regexp
```

Це не проблема FormData як формату. Це типова проблема багаторівневих рядків:
треба рахувати, скільки парсерів ще прочитають текст як код.

## 16. Копія заголовків і автоматичний Content-Type

```js
const formHeaders = Object.create(null);
for (const headerName of Object.keys(headers)) {
    formHeaders[headerName] = headers[headerName];
}
if (!hasFetchHeader(formHeaders, "Content-Type")) {
    formHeaders["content-type"] = "multipart/form-data; boundary=" + boundary;
}
```

`Object.create(null)` дає об'єкт без prototype. Цей об'єкт призначений лише
для даних заголовків.

Ми робимо копію, а не змінюємо `options.headers` напряму. Інакше такий код
отримав би неочікуваний side effect:

```js
const headers = {"X-Page": "catalog"};
fetch("/api", {headers, body: data});
// headers не повинен раптом містити content-type
```

Якщо сайт сам передав Content-Type, runtime його не перезаписує. Це відповідає
ідеї browser fetch: явне рішення користувача має пріоритет. Але сайт тоді сам
відповідає за правильний boundary у своєму Content-Type.

## 17. Чому Python-interceptor не потребував змін

До Python доходить уже такий опис:

```python
{
    "method": "POST",
    "headers": {"content-type": "multipart/form-data; boundary=..."},
    "body": "--boundary\\r\\n...",
}
```

`FetchInterceptor` раніше вже вмів приймати mapping заголовків і string body.
Тому FormData адаптується на JS-боці, а Python не отримує спеціальну гілку
`if isinstance(body, FormData)`. Це правильна межа відповідальності мосту.

## 18. Що перевіряють тести

### Тест JS-класу

Тест додає два `tag`, один `page`, тимчасовий `obsolete`, видаляє його і
викликає `set("tag", "runtime")`. Він доводить:

- число `2` стало рядком `"2"`;
- `delete` видаляє всі значення `obsolete`;
- `set` лишає тільки один `tag`;
- порядок полів правильний;
- `window.FormData === FormData`.

### Тест реального POST

Тест надсилає FormData на локальний `/api/echo`. Сервер повертає raw body і
`Content-Type`. Перевірка не фіксує конкретний boundary, бо він випадковий.
Замість цього вона перевіряє стабільний префікс та дві реальні частини body:

```python
assert result["content_type"].startswith("multipart/form-data; boundary=...")
assert 'name="name"\r\n\r\nAda\r\n' in result["body"]
```

Це тестує справжню інтеграцію, а не лише внутрішній метод класу.

## 19. Вправи для себе

1. Передбач результат `get("tag")` після двох `append` і перевір через
   `page.eval`.
2. Додай третій `tag` без `set` і поясни порядок multipart частин.
3. Передай `headers: {"Content-Type": "text/plain"}` разом із FormData й
   простеж, чому автоматичний Content-Type не додається.
4. Намалюй, на якому рядку `FormData` перестає бути класом і стає рядком.
5. Виклич `new FormData(document.querySelector("form"))` і поясни, чому
   поточний `TypeError` чесніший за порожній запит.

Не потрібно запам'ятати весь документ. Корисніше пройти один запит стрілками:
`append → _entries → serializeFormData → fetch queue → Python → server`.
