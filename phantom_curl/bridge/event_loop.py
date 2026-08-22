"""A small timer bridge for one QuickJS page context."""

from __future__ import annotations

import json
from typing import Optional

from phantom_curl.engine.context import JSContext


class TimerBridge:
    """Install JavaScript timer APIs and expose due callbacks to ``Page``."""

    def __init__(self, context: JSContext) -> None:
        self._context = context
        self._context.eval(
            """
            globalThis.__phantom_timers = Object.create(null);
            globalThis.__phantom_timer_id = 0;

            globalThis.__phantom_schedule_timer = function (callback, delay, args, repeat) {
                if (typeof callback !== 'function') {
                    throw new TypeError('PhantomCurl timers require a function callback');
                }

                const numericDelay = Number(delay);
                const normalizedDelay = Number.isFinite(numericDelay) ? Math.max(0, numericDelay) : 0;
                const id = ++globalThis.__phantom_timer_id;
                globalThis.__phantom_timers[id] = {
                    callback: callback,
                    args: args,
                    delay: repeat ? Math.max(1, normalizedDelay) : normalizedDelay,
                    due: Date.now() + normalizedDelay,
                    repeat: repeat
                };
                return id;
            };

            globalThis.setTimeout = function (callback, delay) {
                return globalThis.__phantom_schedule_timer(callback, delay, Array.prototype.slice.call(arguments, 2), false);
            };
            globalThis.setInterval = function (callback, delay) {
                return globalThis.__phantom_schedule_timer(callback, delay, Array.prototype.slice.call(arguments, 2), true);
            };
            globalThis.clearTimeout = function (id) {
                delete globalThis.__phantom_timers[id];
            };
            globalThis.clearInterval = globalThis.clearTimeout;
            globalThis.queueMicrotask = function (callback) {
                if (typeof callback !== 'function') {
                    throw new TypeError('queueMicrotask requires a function callback');
                }
                Promise.resolve().then(callback);
            };

            globalThis.__phantom_take_due_timers = function () {
                const now = Date.now();
                const due = Object.keys(globalThis.__phantom_timers)
                    .map(Number)
                    .filter(id => globalThis.__phantom_timers[id].due <= now);
                return JSON.stringify(due);
            };
            globalThis.__phantom_run_timer = function (id) {
                const timer = globalThis.__phantom_timers[id];
                if (!timer) {
                    return;
                }
                if (timer.repeat) {
                    timer.due = Date.now() + timer.delay;
                } else {
                    delete globalThis.__phantom_timers[id];
                }
                timer.callback.apply(undefined, timer.args);
            };
            globalThis.__phantom_next_timer_delay = function () {
                const timers = Object.keys(globalThis.__phantom_timers).map(id => globalThis.__phantom_timers[id]);
                if (timers.length === 0) {
                    return null;
                }
                const due = Math.min.apply(null, timers.map(timer => timer.due));
                return Math.max(0, due - Date.now());
            };
            """
        )

    def run_due_timers(self) -> bool:
        """Run every timer due at the current instant and report whether any ran."""
        timer_ids = json.loads(self._context.eval("globalThis.__phantom_take_due_timers()"))
        for timer_id in timer_ids:
            self._context.eval(f"globalThis.__phantom_run_timer({int(timer_id)});")
        return bool(timer_ids)

    def milliseconds_until_next_timer(self) -> Optional[float]:
        """Return the delay before the next timer, or ``None`` when idle."""
        result = self._context.eval("globalThis.__phantom_next_timer_delay()")
        return None if result is None else float(result)
