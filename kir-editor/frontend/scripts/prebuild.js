/**
 * Copy kohakunode Python source + grammar to public/pylib/kohakunode/
 * Also generates manifest.json listing all files relative to pylib/.
 */
import { cpSync, mkdirSync, readdirSync, statSync, writeFileSync, rmSync } from 'fs';
import { join } from 'path';
import { fileURLToPath } from 'url';

const __dirname = fileURLToPath(new URL('.', import.meta.url));
// app/frontend/scripts/ → ../../../src/kohakunode/
const SRC = join(__dirname, '..', '..', '..', 'src', 'kohakunode');
const PYLIB = join(__dirname, '..', 'public', 'pylib');
const DEST = join(PYLIB, 'kohakunode');
const MANIFEST = join(PYLIB, 'manifest.json');

const files = [];

function copyDir(src, dest, relPrefix) {
  mkdirSync(dest, { recursive: true });
  for (const entry of readdirSync(src)) {
    if (entry === '__pycache__') continue;
    const srcPath = join(src, entry);
    const destPath = join(dest, entry);
    const relPath = `${relPrefix}${entry}`;
    if (statSync(srcPath).isDirectory()) {
      copyDir(srcPath, destPath, `${relPath}/`);
    } else if (entry.endsWith('.py') || entry.endsWith('.lark')) {
      cpSync(srcPath, destPath);
      files.push(relPath);
    }
  }
}

// Clean and rebuild
rmSync(DEST, { recursive: true, force: true });
mkdirSync(PYLIB, { recursive: true });
copyDir(SRC, DEST, 'kohakunode/');

writeFileSync(MANIFEST, JSON.stringify({ files }, null, 2));
console.log(`[prebuild] Copied ${files.length} files to public/pylib/`);
