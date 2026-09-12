import * as path from "node:path";

export type AnalyzerSeverity = "error" | "warning" | "info";
export type AnalyzerSymbolKind = "section" | "variable" | "label";

export interface AnalyzerDiagnostic {
  path?: string;
  line: number;
  startCol: number;
  endCol: number;
  severity: AnalyzerSeverity;
  code: string;
  message: string;
}

export interface AnalyzerSymbol {
  path?: string;
  name: string;
  kind: AnalyzerSymbolKind;
  line: number;
  startCol: number;
  endCol: number;
}

export interface AnalyzerResult {
  diagnostics: AnalyzerDiagnostic[];
  definitions: AnalyzerSymbol[];
  symbols: AnalyzerSymbol[];
  dependencies?: string[];
}

export function fileKey(filePath: string): string {
  const resolved = path.resolve(filePath);
  return process.platform === "win32" ? resolved.toLowerCase() : resolved;
}

export class AnalysisCache {
  private readonly entries = new Map<string, { version: number; result: AnalyzerResult }>();
  private readonly generations = new Map<string, number>();
  private readonly pending = new Map<string, number>();

  get(key: string, version: number): AnalyzerResult | undefined {
    const entry = this.entries.get(key);
    return entry?.version === version ? entry.result : undefined;
  }

  begin(key: string): number {
    const generation = (this.generations.get(key) ?? 0) + 1;
    this.generations.set(key, generation);
    this.pending.set(key, generation);
    return generation;
  }

  finish(key: string, generation: number, version: number, result?: AnalyzerResult): boolean {
    if (this.generations.get(key) !== generation) return false;
    this.pending.delete(key);
    if (result) this.entries.set(key, { version, result });
    return true;
  }

  invalidate(filePath: string): Set<string> {
    const affected = new Set(this.pending.keys());
    const changed = fileKey(filePath);
    for (const [key, entry] of this.entries) {
      if (entry.result.dependencies?.some((dependency) => fileKey(dependency) === changed)) {
        affected.add(key);
      }
    }
    for (const key of affected) this.remove(key);
    return affected;
  }

  remove(key: string): void {
    this.entries.delete(key);
    this.pending.delete(key);
    this.generations.set(key, (this.generations.get(key) ?? 0) + 1);
  }

  clear(): void {
    for (const key of this.generations.keys()) this.remove(key);
  }
}

export function findDefinitionByName(
  definitions: AnalyzerSymbol[],
  name: string,
): AnalyzerSymbol | undefined {
  return definitions.find((definition) => definition.name === name);
}

export function listUserSymbolNames(definitions: AnalyzerSymbol[]): string[] {
  return [...new Set(
    definitions
      .filter((definition) => definition.kind === "label" || definition.kind === "variable")
      .map((definition) => definition.name),
  )].sort((left, right) => left.localeCompare(right));
}
