import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const root = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const src = readFileSync(join(root, "web", "js", "inspector.js"), "utf8");

describe("inspector original field", () => {
  it("binds editable data-field=text without readonly", () => {
    assert.match(src, /data-field="text"/);
    assert.match(src, /field === "text"/);
    assert.doesNotMatch(src, /readonly>\$\{escapeText\(region\.text\)\}/);
    assert.match(src, /"text".*"translation"|SLOW = new Set\(\["text"/);
  });
});
