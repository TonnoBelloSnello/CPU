import test from "node:test";
import assert from "node:assert/strict";

import {
  getHoverText,
  getStaticCompletionEntries,
  getSymbolCompletionEntries,
} from "../src/languageData";

test("static completions include key instruction and condition variants", () => {
  const labels = new Set(getStaticCompletionEntries().map((entry) => entry.label));

  assert.ok(labels.has("TEXT"));
  assert.ok(labels.has("WAITKNB"));
  assert.ok(labels.has("ADDEQ"));
  assert.ok(labels.has("space:"));
  assert.ok(labels.has("HEX"));
});

test("hover text resolves conditional instruction variants", () => {
  const hover = getHoverText("MOVEQ");

  assert.ok(hover);
  assert.match(hover, /\*\*MOV\*\*/);
  assert.match(hover, /Execute when Z = 1/);
});

test("hover text covers immediates and registers", () => {
  assert.match(getHoverText("VB1010") ?? "", /Binary Immediate/);
  assert.match(getHoverText("LE") ?? "", /LED register/);
});

test("every instruction completion has valid hover documentation", () => {
  for (const entry of getStaticCompletionEntries()) {
    if (entry.category !== "instruction") {
      continue;
    }
    const hover = getHoverText(entry.label);
    assert.ok(hover, entry.label);
    assert.doesNotMatch(hover, /undefined/);
    assert.doesNotMatch(entry.documentation, /undefined/);
  }
  assert.equal(getHoverText("UNKNOWN"), undefined);
  assert.equal(getHoverText("MOVS"), undefined);
});

test("static completions cover the quantized inference extension", () => {
  const labels = new Set(getStaticCompletionEntries().map((entry) => entry.label));

  assert.ok(labels.has("QRDMULH"));
  assert.ok(labels.has("SXTB"));
  assert.ok(labels.has("VDOT"));
  assert.ok(labels.has("NPURUN"));
  assert.ok(labels.has("Q0"));
  assert.ok(labels.has("A3"));
  assert.ok(labels.has("VLDEQ"));
});

test("hover text explains vector and accumulator registers", () => {
  assert.match(getHoverText("Q5") ?? "", /Vector register/);
  assert.match(getHoverText("A1") ?? "", /Accumulator/);
  assert.match(getHoverText("RELU") ?? "", /no upper bound/);
});

test("symbol completions use current-file definitions", () => {
  const entries = getSymbolCompletionEntries(["buffer", "loop"]);
  assert.deepEqual(entries.map((entry) => entry.label), ["buffer", "loop"]);
});
