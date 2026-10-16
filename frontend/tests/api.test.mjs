import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import ts from "typescript";

// Exercise the actual client without a browser, a running server or new dependencies.
const source = fs.readFileSync(
  new URL("../src/api.ts", import.meta.url),
  "utf8",
);
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.ESNext,
    target: ts.ScriptTarget.ES2022,
  },
}).outputText;
const { api, ApiError } = await import(
  `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`
);

test("API client handles failures safely and cleans request timers", async (t) => {
  const previousWindow = globalThis.window;
  const previousFetch = globalThis.fetch;
  let timeoutCallback;
  let clearedTimers = 0;
  globalThis.window = {
    setTimeout(callback, delay) {
      assert.equal(delay, 15_000);
      timeoutCallback = callback;
      return 99;
    },
    clearTimeout(id) {
      assert.equal(id, 99);
      clearedTimers += 1;
    },
  };
  t.after(() => {
    globalThis.fetch = previousFetch;
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
  });

  await t.test(
    "reads successful JSON and sends the selected workspace",
    async () => {
      globalThis.fetch = async (url, options) => {
        assert.equal(url, "/api/v1/health");
        assert.equal(options.headers["X-Workspace"], "normal");
        assert.ok(options.signal instanceof AbortSignal);
        return { ok: true, json: async () => ({ ok: true }) };
      };
      assert.deepEqual(await api("/health", "normal"), { ok: true });
      assert.equal(clearedTimers, 1);
    },
  );

  await t.test("keeps a 409 as a recoverable conflict", async () => {
    globalThis.fetch = async () => ({ ok: false, status: 409 });
    await assert.rejects(
      api("/reports/1/draft", "normal"),
      (error) => error instanceof ApiError && error.status === 409,
    );
    assert.equal(clearedTimers, 2);
  });

  await t.test("does not expose malformed response contents", async () => {
    globalThis.fetch = async () => ({
      ok: true,
      status: 200,
      json: async () => {
        throw new SyntaxError("private-provider-response");
      },
    });
    await assert.rejects(
      api("/health", "normal"),
      (error) =>
        error instanceof ApiError &&
        !error.message.includes("private-provider-response"),
    );
    assert.equal(clearedTimers, 3);
  });

  const awaitAbort = (_url, { signal }) =>
    new Promise((_resolve, reject) => {
      const abort = () => reject(new DOMException("Aborted", "AbortError"));
      if (signal.aborted) abort();
      else signal.addEventListener("abort", abort, { once: true });
    });

  await t.test("aborts a pending request after the timeout", async () => {
    globalThis.fetch = awaitAbort;
    const pending = api("/health", "normal");
    timeoutCallback();
    await assert.rejects(
      pending,
      (error) =>
        error instanceof ApiError &&
        error.status === 0 &&
        error.message.includes("超时"),
    );
    assert.equal(clearedTimers, 4);
  });

  await t.test(
    "propagates caller cancellation and removes its listener",
    async () => {
      globalThis.fetch = awaitAbort;
      const parent = new AbortController();
      const originalRemove = parent.signal.removeEventListener.bind(
        parent.signal,
      );
      let removedAbortListeners = 0;
      parent.signal.removeEventListener = (...args) => {
        if (args[0] === "abort") removedAbortListeners += 1;
        return originalRemove(...args);
      };
      const pending = api("/health", "normal", { signal: parent.signal });
      parent.abort();
      await assert.rejects(
        pending,
        (error) => error instanceof ApiError && error.status === 0,
      );
      assert.equal(clearedTimers, 5);
      assert.equal(removedAbortListeners, 1);
    },
  );
});
