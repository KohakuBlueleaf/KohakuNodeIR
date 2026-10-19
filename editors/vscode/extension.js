const vscode = require("vscode");
const { LanguageClient } = require("vscode-languageclient/node");

let client;

function createClient() {
  const config = vscode.workspace.getConfiguration("kir");
  const executable = {
    command: config.get("server.path", "kir-lsp"),
    args: config.get("server.args", []),
  };
  const initializationOptions = { sigPath: config.get("sigPath", []) };
  const core = config.get("core", "auto");
  // "auto" leaves the choice to the server.
  if (core !== "auto") initializationOptions.core = core;
  return new LanguageClient(
    "kir",
    "KIR Language Server",
    { run: executable, debug: executable },
    { documentSelector: [{ language: "kir" }], initializationOptions },
  );
}

async function startClient() {
  client = createClient();
  try {
    await client.start();
  } catch (err) {
    const command = vscode.workspace.getConfiguration("kir").get("server.path", "kir-lsp");
    vscode.window.showErrorMessage(
      `KIR language server failed to start (${command}): ${err.message}. ` +
        'Install it with `pip install "kohakunode[lsp]"` or set `kir.server.path`.',
    );
  }
}

async function stopClient() {
  if (!client) return;
  const running = client;
  client = undefined;
  if (running.isRunning()) await running.stop();
}

async function restartClient() {
  await stopClient();
  await startClient();
}

async function activate(context) {
  context.subscriptions.push(
    vscode.commands.registerCommand("kir.restartServer", restartClient),
    vscode.workspace.onDidChangeConfiguration((event) => {
      if (["kir.server", "kir.sigPath", "kir.core"].some((section) => event.affectsConfiguration(section))) {
        restartClient();
      }
    }),
  );
  await startClient();
}

function deactivate() {
  return stopClient();
}

module.exports = { activate, deactivate };
