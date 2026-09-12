import * as fs from "node:fs";
import * as path from "node:path";
import { spawn } from "node:child_process";
import * as vscode from "vscode";

import {
  AnalyzerDiagnostic,
  AnalyzerResult,
  AnalyzerSymbol,
  AnalysisCache,
  fileKey,
  findDefinitionByName,
  listUserSymbolNames,
} from "./analyzerProtocol";
import {
  CompletionEntry,
  getHoverText,
  getStaticCompletionEntries,
  getSymbolCompletionEntries,
} from "./languageData";

const LANGUAGE_ID = "de1";
const ANALYZER_RELATIVE_PATH = path.join("src", "cpu", "encoder", "analyze.py");
const ANALYZER_MODULE = "src.cpu.encoder.analyze";
const ANALYSIS_DELAY_MS = 250;

function isDe1Document(document: vscode.TextDocument): boolean {
  return document.languageId === LANGUAGE_ID;
}

function rangeFromSymbol(symbol: AnalyzerSymbol): vscode.Range {
  return new vscode.Range(symbol.line, symbol.startCol, symbol.line, symbol.endCol);
}

function lineRange(document: vscode.TextDocument, line: number): vscode.Range {
  return document.lineAt(line).range;
}

function mapSeverity(severity: AnalyzerDiagnostic["severity"]): vscode.DiagnosticSeverity {
  switch (severity) {
    case "warning":
      return vscode.DiagnosticSeverity.Warning;
    case "info":
      return vscode.DiagnosticSeverity.Information;
    default:
      return vscode.DiagnosticSeverity.Error;
  }
}

function mapSymbolKind(kind: AnalyzerSymbol["kind"]): vscode.SymbolKind {
  switch (kind) {
    case "section":
      return vscode.SymbolKind.Namespace;
    case "variable":
      return vscode.SymbolKind.Variable;
    default:
      return vscode.SymbolKind.Function;
  }
}

function getTokenAtPosition(document: vscode.TextDocument, position: vscode.Position): string | undefined {
  const line = document.lineAt(position.line).text;
  const tokenPattern = /"[^"]*"|'[^']*'|VB[01]+|V-?\d+|F(?:[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?|[-+]?(?:inf|nan))|[A-Za-z_][A-Za-z0-9_]*/gi;

  for (const match of line.matchAll(tokenPattern)) {
    const start = match.index ?? 0;
    const end = start + match[0].length;
    if (position.character >= start && position.character <= end) {
      return match[0];
    }
  }

  return undefined;
}

function getCurrentWord(document: vscode.TextDocument, position: vscode.Position): string | undefined {
  const range = document.getWordRangeAtPosition(position, /[A-Za-z_][A-Za-z0-9_]*/);
  return range ? document.getText(range) : undefined;
}

async function runAnalyzer(
  pythonPath: string,
  workspaceRoot: string,
  document: vscode.TextDocument,
): Promise<AnalyzerResult> {
  const payload = JSON.stringify({
    path: document.isUntitled ? document.uri.toString() : document.uri.fsPath,
    text: document.getText(),
    documents: Object.fromEntries(vscode.workspace.textDocuments
      .filter((openDocument) => isDe1Document(openDocument) && openDocument.uri.scheme === "file")
      .map((openDocument) => [openDocument.uri.fsPath, openDocument.getText()])),
  });

  return new Promise<AnalyzerResult>((resolve, reject) => {
    const child = spawn(pythonPath, ["-m", ANALYZER_MODULE], {
      cwd: workspaceRoot,
      stdio: "pipe",
    });

    let stdout = "";
    let stderr = "";

    child.stdout.on("data", (chunk: Buffer | string) => {
      stdout += chunk.toString();
    });
    child.stderr.on("data", (chunk: Buffer | string) => {
      stderr += chunk.toString();
    });
    child.on("error", (error) => {
      reject(error);
    });
    child.on("close", (code) => {
      if (!stdout.trim()) {
        reject(new Error(stderr || `Analyzer exited with code ${code ?? "unknown"}.`));
        return;
      }

      try {
        resolve(JSON.parse(stdout) as AnalyzerResult);
      } catch (error) {
        reject(new Error(`Analyzer returned invalid JSON: ${String(error)}\n${stdout}\n${stderr}`));
      }
    });

    child.stdin.write(payload);
    child.stdin.end();
  });
}

class AnalyzerController implements vscode.Disposable {
  private readonly diagnostics = vscode.languages.createDiagnosticCollection(LANGUAGE_ID);
  private readonly outputChannel = vscode.window.createOutputChannel("DE1");
  private readonly cache = new AnalysisCache();
  private readonly timers = new Map<string, NodeJS.Timeout>();
  private readonly warningKeys = new Set<string>();
  private readonly results = new Map<string, AnalyzerResult>();
  private readonly watchers = new Map<string, vscode.FileSystemWatcher>();

  dispose(): void {
    for (const timer of this.timers.values()) {
      clearTimeout(timer);
    }
    this.timers.clear();
    this.cache.clear();
    for (const watcher of this.watchers.values()) watcher.dispose();
    this.watchers.clear();
    this.results.clear();
    this.diagnostics.dispose();
    this.outputChannel.dispose();
  }

  getCachedResult(document: vscode.TextDocument): AnalyzerResult | undefined {
    return this.cache.get(document.uri.toString(), document.version);
  }

  async getResult(document: vscode.TextDocument): Promise<AnalyzerResult | undefined> {
    if (!isDe1Document(document)) {
      return undefined;
    }

    const cached = this.getCachedResult(document);
    if (cached) {
      return cached;
    }

    return this.analyze(document);
  }

  schedule(document: vscode.TextDocument, delayMs = ANALYSIS_DELAY_MS): void {
    if (!isDe1Document(document)) {
      return;
    }

    const cacheKey = document.uri.toString();
    const existing = this.timers.get(cacheKey);
    if (existing) {
      clearTimeout(existing);
    }

    const timer = setTimeout(() => {
      this.timers.delete(cacheKey);
      void this.analyze(document);
    }, delayMs);
    this.timers.set(cacheKey, timer);
  }

  clear(document: vscode.TextDocument): void {
    const cacheKey = document.uri.toString();
    const timer = this.timers.get(cacheKey);
    if (timer) {
      clearTimeout(timer);
      this.timers.delete(cacheKey);
    }
    this.cache.remove(cacheKey);
    this.results.delete(cacheKey);
    this.refreshDiagnostics();
    this.refreshWatchers();
  }

  changed(document: vscode.TextDocument, closed = false): void {
    if (!isDe1Document(document)) return;
    this.cache.remove(document.uri.toString());
    if (document.uri.scheme === "file") this.fileChanged(document.uri.fsPath);
    if (!closed) this.schedule(document);
  }

  fileChanged(filePath: string): void {
    const affected = this.cache.invalidate(filePath);
    for (const document of vscode.workspace.textDocuments) {
      if (affected.has(document.uri.toString()) ||
          (document.uri.scheme === "file" && fileKey(document.uri.fsPath) === fileKey(filePath))) {
        this.cache.remove(document.uri.toString());
        this.schedule(document);
      }
    }
  }

  private refreshWatchers(): void {
    const dependencies = new Map<string, string>();
    for (const result of this.results.values()) {
      for (const dependency of result.dependencies ?? []) dependencies.set(fileKey(dependency), dependency);
    }
    for (const [key, watcher] of this.watchers) {
      if (!dependencies.has(key)) {
        watcher.dispose();
        this.watchers.delete(key);
      }
    }
    for (const [key, dependency] of dependencies) {
      if (this.watchers.has(key)) continue;
      const watcher = vscode.workspace.createFileSystemWatcher(
        new vscode.RelativePattern(path.dirname(dependency), path.basename(dependency)),
      );
      const changed = () => this.fileChanged(dependency);
      watcher.onDidChange(changed);
      watcher.onDidCreate(changed);
      watcher.onDidDelete(changed);
      this.watchers.set(key, watcher);
    }
  }

  private warnOnce(key: string, message: string, detail?: string): void {
    if (this.warningKeys.has(key)) {
      if (detail) {
        this.outputChannel.appendLine(detail);
      }
      return;
    }

    this.warningKeys.add(key);
    this.outputChannel.appendLine(message);
    if (detail) {
      this.outputChannel.appendLine(detail);
    }
    void vscode.window.showWarningMessage(message);
  }

  private refreshDiagnostics(): void {
    const grouped = new Map<string, { uri: vscode.Uri; items: vscode.Diagnostic[]; seen: Set<string> }>();
    for (const [owner, result] of this.results) {
      for (const diagnostic of result.diagnostics) {
        const uri = diagnostic.path ? vscode.Uri.file(diagnostic.path) : vscode.Uri.parse(owner);
        const key = uri.scheme === "file" ? fileKey(uri.fsPath) : uri.toString();
        const group = grouped.get(key) ?? { uri, items: [], seen: new Set<string>() };
        grouped.set(key, group);
        const identity = JSON.stringify(diagnostic);
        if (group.seen.has(identity)) continue;
        group.seen.add(identity);
        const range = new vscode.Range(
          diagnostic.line, diagnostic.startCol, diagnostic.line,
          Math.max(diagnostic.startCol + 1, diagnostic.endCol),
        );
        const item = new vscode.Diagnostic(range, diagnostic.message, mapSeverity(diagnostic.severity));
        item.code = diagnostic.code;
        group.items.push(item);
      }
    }
    this.diagnostics.clear();
    for (const group of grouped.values()) this.diagnostics.set(group.uri, group.items);
  }

  private resolveWorkspaceRoot(document: vscode.TextDocument): string | undefined {
    const folder = vscode.workspace.getWorkspaceFolder(document.uri) ?? vscode.workspace.workspaceFolders?.[0];
    return folder?.uri.fsPath;
  }

  private resolvePythonPath(document: vscode.TextDocument, workspaceRoot: string): string {
    const configured = vscode.workspace.getConfiguration("de1", document.uri).get<string>("pythonPath", "").trim();
    if (configured) {
      return path.isAbsolute(configured) ? configured : path.join(workspaceRoot, configured);
    }

    const venv = process.platform === "win32"
      ? path.join(workspaceRoot, ".venv", "Scripts", "python.exe")
      : path.join(workspaceRoot, ".venv", "bin", "python");
    return fs.existsSync(venv) ? venv : "python";
  }

  private isDiagnosticsEnabled(document: vscode.TextDocument): boolean {
    return vscode.workspace.getConfiguration("de1", document.uri).get<boolean>("diagnostics.enabled", true);
  }

  private async analyze(document: vscode.TextDocument): Promise<AnalyzerResult | undefined> {
    if (document.isClosed) return undefined;
    if (!this.isDiagnosticsEnabled(document)) {
      this.clear(document);
      return undefined;
    }

    const workspaceRoot = this.resolveWorkspaceRoot(document);
    if (!workspaceRoot) {
      this.warnOnce("workspace", "DE1 diagnostics require the file to be inside an open workspace folder.");
      this.clear(document);
      return undefined;
    }

    const scriptPath = path.join(workspaceRoot, ANALYZER_RELATIVE_PATH);
    if (!fs.existsSync(scriptPath)) {
      this.warnOnce(
        "missing-analyzer",
        "DE1 diagnostics are unavailable because src/cpu/encoder/analyze.py was not found.",
        scriptPath,
      );
      this.clear(document);
      return undefined;
    }

    const pythonPath = this.resolvePythonPath(document, workspaceRoot);
    const versionAtStart = document.version;
    const uriKey = document.uri.toString();
    const generation = this.cache.begin(uriKey);

    try {
      const result = await runAnalyzer(pythonPath, workspaceRoot, document);
      const liveDocument = vscode.workspace.textDocuments.find((openDocument) => openDocument.uri.toString() === uriKey);
      if (!liveDocument || liveDocument.version !== versionAtStart) {
        this.cache.finish(uriKey, generation, versionAtStart);
        return this.getCachedResult(document);
      }

      if (!this.cache.finish(uriKey, generation, liveDocument.version, result)) {
        return this.getCachedResult(document);
      }
      this.results.set(uriKey, result);
      this.refreshDiagnostics();
      this.refreshWatchers();
      return result;
    } catch (error) {
      if (!this.cache.finish(uriKey, generation, versionAtStart)) return this.getCachedResult(document);
      this.warnOnce(
        "python-launch",
        `DE1 diagnostics could not run with interpreter '${pythonPath}'.`,
        String(error),
      );
      return this.getCachedResult(document);
    }
  }
}

const COMPLETION_KINDS: Record<CompletionEntry["category"], vscode.CompletionItemKind> = {
  instruction: vscode.CompletionItemKind.Keyword,
  directive: vscode.CompletionItemKind.Snippet,
  register: vscode.CompletionItemKind.Variable,
  symbol: vscode.CompletionItemKind.Reference,
};

function toCompletionItem(entry: CompletionEntry): vscode.CompletionItem {
  const item = new vscode.CompletionItem(entry.label, COMPLETION_KINDS[entry.category]);
  item.detail = entry.detail;
  item.documentation = new vscode.MarkdownString(entry.documentation);
  item.insertText = new vscode.SnippetString(entry.insertText);
  return item;
}

export function activate(context: vscode.ExtensionContext): void {
  const controller = new AnalyzerController();
  context.subscriptions.push(controller);

  const sourceWatcher = vscode.workspace.createFileSystemWatcher("**/*.de1");
  const fileChanged = (uri: vscode.Uri) => controller.fileChanged(uri.fsPath);
  context.subscriptions.push(
    sourceWatcher,
    sourceWatcher.onDidChange(fileChanged),
    sourceWatcher.onDidCreate(fileChanged),
    sourceWatcher.onDidDelete(fileChanged),
  );

  context.subscriptions.push(
    vscode.workspace.onDidOpenTextDocument((document) => {
      controller.changed(document);
    }),
    vscode.workspace.onDidSaveTextDocument((document) => {
      controller.changed(document);
    }),
    vscode.workspace.onDidChangeTextDocument((event) => {
      controller.changed(event.document);
    }),
    vscode.workspace.onDidCloseTextDocument((document) => {
      controller.clear(document);
      controller.changed(document, true);
    }),
  );

  context.subscriptions.push(
    vscode.languages.registerCompletionItemProvider(
      { language: LANGUAGE_ID },
      {
        async provideCompletionItems(document, position) {
          const items = getStaticCompletionEntries().map(toCompletionItem);
          const result = await controller.getResult(document);
          const symbolEntries = getSymbolCompletionEntries(listUserSymbolNames(result?.definitions ?? []));
          items.push(...symbolEntries.map(toCompletionItem));

          const linePrefix = document.lineAt(position.line).text.slice(0, position.character).trim();
          if (linePrefix.endsWith(":")) {
            return items.filter((item) => item.label.toString().endsWith(":"));
          }

          return items;
        },
      },
      ":",
      "[",
      " ",
      ",",
      "\"",
    ),
    vscode.languages.registerHoverProvider({ language: LANGUAGE_ID }, {
      provideHover(document, position) {
        const token = getTokenAtPosition(document, position);
        if (!token) {
          return undefined;
        }

        const hoverText = getHoverText(token);
        if (!hoverText) {
          return undefined;
        }

        return new vscode.Hover(new vscode.MarkdownString(hoverText));
      },
    }),
    vscode.languages.registerDocumentSymbolProvider({ language: LANGUAGE_ID }, {
      async provideDocumentSymbols(document) {
        const result = await controller.getResult(document);
        return (result?.symbols ?? []).map((symbol) => new vscode.DocumentSymbol(
          symbol.name,
          symbol.kind,
          mapSymbolKind(symbol.kind),
          lineRange(document, symbol.line),
          rangeFromSymbol(symbol),
        ));
      },
    }),
    vscode.languages.registerDefinitionProvider({ language: LANGUAGE_ID }, {
      async provideDefinition(document, position) {
        const name = getCurrentWord(document, position);
        if (!name) {
          return undefined;
        }

        const result = await controller.getResult(document);
        const definition = findDefinitionByName(result?.definitions ?? [], name);
        if (!definition) {
          return undefined;
        }

        return new vscode.Location(
          definition.path ? vscode.Uri.file(definition.path) : document.uri,
          rangeFromSymbol(definition),
        );
      },
    }),
  );

  for (const document of vscode.workspace.textDocuments) {
    controller.schedule(document, 10);
  }
}

export function deactivate(): void {
}
