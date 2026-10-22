import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import ts from "typescript";
const source = fs.readFileSync(
  new URL("../src/format.ts", import.meta.url),
  "utf8",
);
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.ESNext,
    target: ts.ScriptTarget.ES2022,
  },
}).outputText;
const { shiftDate, periodText, metricValue } = await import(
  `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`
);
test("inclusive dates round-trip across months, years and leap days", () => {
  for (const end of ["2027-01-01", "2026-11-01", "2024-03-01"]) {
    assert.equal(shiftDate(shiftDate(end, -1), 1), end);
  }
  assert.equal(shiftDate("2027-01-01", -1), "2026-12-31");
  assert.equal(shiftDate("2024-03-01", -1), "2024-02-29");
  assert.equal(shiftDate("", 1), "");
  assert.equal(
    periodText("2026-10-08", "2026-10-22"),
    "2026-10-08 至 2026-10-21（含首尾日期）",
  );
});
test("metric display rounds prose without changing numeric evidence", () => {
  assert.equal(metricValue(3.970588235, "分"), "3.97");
  assert.equal(metricValue(0.98765, "ratio"), "98.77%");
  assert.equal(metricValue(12, "个"), "12");
  assert.equal(metricValue(null, "人"), "材料不足，暂不计算");
});
