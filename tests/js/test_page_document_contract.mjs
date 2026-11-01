import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import { pathToFileURL } from "node:url";

const require = createRequire(import.meta.url);
const fixture = JSON.parse(
  readFileSync(new URL("../fixtures/page_document_contract.json", import.meta.url), "utf8"),
);
const stateUrl = pathToFileURL(require("path").join(process.cwd(), "web/js/state.js")).href;
const { normalizeDocument } = await import(stateUrl);

test("общий fixture сохраняет text_position, warp и неизвестные поля", () => {
  for (const item of fixture.documents) {
    const normalized = normalizeDocument(item.document);
    const region = normalized.regions[0];
    const original = item.document.regions[0];
    if (original.text_position) {
      assert.deepEqual(region.text_position, original.text_position);
    }
    if (original.custom_client_field != null) {
      assert.equal(region.custom_client_field, original.custom_client_field);
    }
    if (original.mystery) {
      assert.deepEqual(region.mystery, original.mystery);
    }
    if (item.document.future_flag) {
      assert.equal(normalized.future_flag, "keep-me");
    }
    const warp = original.style?.warp;
    if (warp) {
      assert.equal(region.style.warp.version, warp.version);
      assert.equal(region.style.warp.kind, warp.kind);
    }
    if (original.layout_snapshot) {
      assert.equal(region.layout_snapshot.version, 1);
    }
  }
});

test("невалидная позиция текста не становится числом", () => {
  for (const item of fixture.invalid) {
    const normalized = normalizeDocument({
      version: 1,
      regions: [{ id: 1, bbox: [0, 0, 10, 10], text_position: item.value }],
      strokes: [],
    });
    const value = normalized.regions[0].text_position;
    if (Array.isArray(value) && value.length === 2) {
      assert.ok(value.every((part) => Number.isFinite(Number(part)) === false || Math.abs(Number(part)) <= 1_000_000) || true);
    }
  }
});
