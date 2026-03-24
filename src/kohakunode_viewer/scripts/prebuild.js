/**
 * Copy kohakunode Python source + grammar to public/pylib/ for Pyodide.
 * Also generates a manifest.json listing all files.
 */
import { cpSync, mkdirSync, readdirSync, statSync, writeFileSync } from "fs";
import { join, relative } from "path";
import { fileURLToPath } from "url";

const __dirname = fileURLToPath(new URL(".", import.meta.url));
const SRC = join(__dirname, "..", "..", "kohakunode");
const DEST = join(__dirname, "..", "public", "pylib", "kohakunode");
const MANIFEST = join(__dirname, "..", "public", "pylib", "manifest.json");

const files = [];

function copyDir(src, dest, relBase) {
  mkdirSync(dest, { recursive: true });
  for (const entry of readdirSync(src)) {
    const srcPath = join(src, entry);
    const destPath = join(dest, entry);
    const relPath = relBase ? `${relBase}/${entry}` : entry;
    if (statSync(srcPath).isDirectory()) {
      copyDir(srcPath, destPath, `kohakunode/${relPath}`);
    } else if (entry.endsWith(".py") || entry.endsWith(".lark")) {
      cpSync(srcPath, destPath);
      files.push(`kohakunode/${relPath}`);
    }
  }
}

mkdirSync(join(__dirname, "..", "public", "pylib"), { recursive: true });
copyDir(SRC, DEST, "");

writeFileSync(MANIFEST, JSON.stringify({ files }, null, 2));
console.log(`[prebuild] Copied ${files.length} files to public/pylib/`);
