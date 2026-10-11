import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const root = join(dirname(fileURLToPath(import.meta.url)), "../..");

describe("shell chrome markup", () => {
  it("keeps floating dock and panel toggles with smoke data-roles", () => {
    const html = readFileSync(join(root, "web/index.html"), "utf8");
    assert.match(html, /data-role="tool-dock"/);
    assert.match(html, /viewer__bar dock/);
    assert.match(html, /data-toggle-panel="is-pages-collapsed"/);
    assert.match(html, /data-toggle-panel="is-inspector-collapsed"/);
    assert.match(html, /data-role="tool-brush"/);
    assert.match(html, /data-role="apply-edits"/);
    assert.match(html, /shell-v2\.css/);
  });
});
