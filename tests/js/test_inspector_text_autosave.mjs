import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const root = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const src = readFileSync(join(root, "web", "js", "inspector.js"), "utf8");

describe("inspector text autosave", () => {
  it("does not defer text and translation fields", () => {
    assert.match(
      src,
      /deferApply:\s*field\s*!==\s*"text"\s*&&\s*field\s*!==\s*"translation"/,
    );
  });
});
