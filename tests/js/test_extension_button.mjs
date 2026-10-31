import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import test from "node:test";

const context = vm.createContext({ globalThis: {} });
context.globalThis = context;
vm.runInContext(readFileSync(new URL("../../extension/src/button-model.js", import.meta.url), "utf8"), context);
const model = context.iltButtonModel;

test("подписи этапов по-русски", () => {
  assert.equal(model.stageLabel("detect"), "Ищем текст");
  assert.equal(model.stageLabel("ocr"), "Распознаём");
  assert.equal(model.stageLabel("translate"), "Переводим");
  assert.equal(model.stageLabel("inpaint"), "Стираем оригинал");
  assert.equal(model.stageLabel("typeset"), "Вписываем перевод");
  assert.equal(model.stageLabel("cache", "", true), "Из кэша");
  assert.equal(model.stageLabel("custom", "Свой этап"), "Свой этап");
});

test("адрес без query и оценка времени", () => {
  assert.equal(model.redactUrl("https://cdn.example/a.png?token=1#x"), "https://cdn.example/a.png");
  assert.equal(model.formatEta(1000), "");
  assert.equal(model.formatEta(8000), "8 с");
  assert.equal(model.pickCorner({ tr: true, tl: false }), "tl");
  assert.equal(model.pickCorner({ tr: true, tl: true, br: true, bl: true }), "tr");
});
