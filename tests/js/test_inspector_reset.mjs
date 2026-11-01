import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const root = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const src = readFileSync(join(root, "web", "js", "inspector.js"), "utf8");

describe("inspector reset without auto snapshot", () => {
  it("disables reset when has_auto is false", () => {
    assert.match(src, /const canReset = page\.has_auto !== false/);
    assert.match(src, /data-page-action="reset"\$\{canReset \? "" : " disabled"\}/);
    assert.match(src, /Автоматического снимка нет: сброс правок недоступен/);
    assert.match(src, /if \(canReset\) resetButton\.addEventListener\("click", reset\)/);
    assert.match(src, /page\?\.has_auto === false/);
  });
});
