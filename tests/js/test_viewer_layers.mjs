import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../../web/js/state.js", import.meta.url), "utf8");

test("слои рамок и маски пишутся в существующие настройки", () => {
  assert.match(source, /viewer_show_boxes: state\.showBoxes/);
  assert.match(source, /viewer_show_mask: state\.showMask/);
  assert.match(source, /putSettings\(settingsForSave\(settings\)\)/);
  assert.match(source, /showBoxes: settings\.viewer_show_boxes !== false/);
});
