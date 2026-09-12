import test from "node:test";
import assert from "node:assert/strict";
import * as path from "node:path";

import {
  findDefinitionByName,
  listUserSymbolNames,
  AnalysisCache,
  AnalyzerResult,
} from "../src/analyzerProtocol";

test("findDefinitionByName returns the matching file symbol", () => {
  const definition = findDefinitionByName(
    [
      { name: "space", kind: "section", line: 0, startCol: 0, endCol: 5 },
      { name: "loop", kind: "label", line: 4, startCol: 0, endCol: 4 },
    ],
    "loop",
  );

  assert.ok(definition);
  assert.equal(definition.name, "loop");
  assert.equal(definition.kind, "label");
});

test("included definitions retain their destination and appear in completion", () => {
  const filePath = path.resolve("data/weights.de1");
  const definitions = [{ name: "weights", kind: "variable" as const,
    path: filePath, line: 2, startCol: 4, endCol: 11 }];
  assert.equal(findDefinitionByName(definitions, "weights")?.path, filePath);
  assert.equal(findDefinitionByName(definitions, "weights")?.line, 2);
  assert.deepEqual(listUserSymbolNames(definitions), ["weights"]);
});

function result(dependencies: string[] = []): AnalyzerResult {
  return { diagnostics: [], definitions: [], symbols: [], dependencies };
}

test("dependency changes invalidate cached parents without changing their version", () => {
  const cache = new AnalysisCache();
  const weights = path.resolve("data/weights.de1");
  const generation = cache.begin("main");
  cache.finish("main", generation, 1, result([weights]));
  const unrelated = cache.begin("other");
  cache.finish("other", unrelated, 1, result());
  assert.ok(cache.get("main", 1));
  assert.deepEqual([...cache.invalidate(weights)], ["main"]);
  assert.equal(cache.get("main", 1), undefined);
  assert.ok(cache.get("other", 1));
});

test("edits during include discovery and out-of-order replies cannot repopulate the cache", () => {
  const cache = new AnalysisCache();
  const first = cache.begin("main");
  assert.deepEqual([...cache.invalidate("new-include.de1")], ["main"]);
  const second = cache.begin("main");
  assert.equal(cache.finish("main", first, 1, result()), false);
  assert.equal(cache.finish("main", second, 1, result()), true);
  const third = cache.begin("main");
  const fourth = cache.begin("main");
  assert.equal(cache.finish("main", fourth, 1, result()), true);
  assert.equal(cache.finish("main", third, 1, result()), false);
});

test("missing dependencies invalidate after creation and closed requests stay discarded", () => {
  const cache = new AnalysisCache();
  cache.finish("main", cache.begin("main"), 1, result([path.resolve("missing.de1")]));
  assert.ok(cache.invalidate("missing.de1").has("main"));
  const generation = cache.begin("main");
  cache.remove("main");
  assert.equal(cache.finish("main", generation, 1, result()), false);
});

test("listUserSymbolNames returns unique variable and label names", () => {
  const names = listUserSymbolNames([
    { name: "space", kind: "section", line: 0, startCol: 0, endCol: 5 },
    { name: "buffer", kind: "variable", line: 1, startCol: 4, endCol: 10 },
    { name: "loop", kind: "label", line: 4, startCol: 0, endCol: 4 },
    { name: "loop", kind: "label", line: 8, startCol: 0, endCol: 4 },
  ]);

  assert.deepEqual(names, ["buffer", "loop"]);
});
