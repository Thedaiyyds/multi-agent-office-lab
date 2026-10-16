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
const { api, ApiError, downloadMaterial } = await import(
  `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`
);

test("material requests preserve upload boundaries, validation issues and workspace downloads", async (t) => {
  const original = {
    window: globalThis.window,
    fetch: globalThis.fetch,
    document: globalThis.document,
  };
  const createURL = URL.createObjectURL;
  const revokeURL = URL.revokeObjectURL;
  let cleared = 0;
  globalThis.window = {
    setTimeout(callback, delay) {
      if (delay === 1000) callback();
      return 1;
    },
    clearTimeout() {
      cleared += 1;
    },
  };
  t.after(() => {
    for (const key of ["window", "fetch", "document"]) {
      if (original[key] === undefined) delete globalThis[key];
      else globalThis[key] = original[key];
    }
    URL.createObjectURL = createURL;
    URL.revokeObjectURL = revokeURL;
  });

  await t.test("lets the browser supply the multipart boundary", async () => {
    const body = new FormData();
    body.append("file", new Blob(["材料"]), "中文材料.txt");
    globalThis.fetch = async (url, options) => {
      assert.equal(url, "/api/v1/materials/import");
      assert.equal(options.headers["Content-Type"], undefined);
      assert.equal(options.headers["X-Workspace"], "demo");
      assert.equal(options.body, body);
      return { ok: true, json: async () => ({ id: "import-1" }) };
    };
    assert.deepEqual(
      await api("/materials/import", "demo", { method: "POST", body }),
      { id: "import-1" },
    );
  });

  await t.test("keeps actionable material row errors", async () => {
    const issue = {
      severity: "error",
      location: "CSV第3行",
      message: "日期无效",
    };
    globalThis.fetch = async () => ({
      ok: false,
      status: 422,
      json: async () => ({
        detail: {
          message: "材料未入库",
          issues: [issue, { location: 42, message: "ignore" }],
        },
      }),
    });
    await assert.rejects(api("/imports/id/confirm", "demo"), (error) => {
      assert.ok(error instanceof ApiError);
      assert.equal(error.message, "材料未入库");
      assert.deepEqual(error.issues, [issue]);
      return true;
    });
  });

  await t.test(
    "keeps statistics scope and version errors actionable",
    async () => {
      for (const [status, detail] of [
        [422, "工作日期须位于报告起止期间内，且不包含结束日"],
        [409, "报告已更新，请刷新后按当前版本重新统计"],
      ]) {
        globalThis.fetch = async () => ({
          ok: false,
          status,
          json: async () => ({ detail }),
        });
        await assert.rejects(api("/reports/id/statistics", "normal"), (error) => {
          assert.ok(error instanceof ApiError);
          assert.equal(error.status, status);
          assert.equal(error.message, detail);
          return true;
        });
      }
    },
  );

  await t.test(
    "downloads bytes with the selected workspace header",
    async () => {
      const blob = new Blob(["原始材料"]);
      let clicked = false,
        removed = false,
        revoked = false;
      const anchor = {
        click() {
          clicked = true;
        },
        remove() {
          removed = true;
        },
      };
      globalThis.document = {
        createElement: () => anchor,
        body: { appendChild() {} },
      };
      URL.createObjectURL = (value) => {
        assert.equal(value, blob);
        return "blob:test";
      };
      URL.revokeObjectURL = (value) => {
        assert.equal(value, "blob:test");
        revoked = true;
      };
      globalThis.fetch = async (url, options) => {
        assert.equal(url, "/api/v1/materials/material-1/download");
        assert.equal(options.headers["X-Workspace"], "demo");
        return { ok: true, blob: async () => blob };
      };
      await downloadMaterial("material-1", "原件.csv", "demo");
      assert.equal(anchor.download, "原件.csv");
      assert.ok(clicked && removed && revoked);
    },
  );
  assert.equal(cleared, 5);
});

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
