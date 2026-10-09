import { readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, extname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const fontAwesome = join(root, 'node_modules', '@fortawesome', 'fontawesome-free');
const stylesheets = ['fontawesome.min.css', 'solid.min.css', 'regular.min.css'];
const sources = new Set(['.html', '.ts']);
const iconPattern = /fa-[a-z0-9]+(?:-[a-z0-9]+)*/g;
const quoted = /(["'`])((?:(?!\1).)*\bfa-[a-z0-9-]+(?:(?!\1).)*)\1/g;

function selectors() {
  const known = new Set();
  for (const sheet of stylesheets) {
    const css = readFileSync(join(fontAwesome, 'css', sheet), 'utf8');
    for (const match of css.matchAll(/\.(fa-[a-z0-9]+(?:-[a-z0-9]+)*)/g)) {
      known.add(match[1]);
    }
  }
  return known;
}

function regularIcons() {
  const families = JSON.parse(readFileSync(join(fontAwesome, 'metadata', 'icon-families.json'), 'utf8'));
  const regular = new Set();
  for (const [name, icon] of Object.entries(families)) {
    const free = icon.familyStylesByLicense?.free ?? [];
    if (free.some((style) => style.family === 'classic' && style.style === 'regular')) {
      regular.add(`fa-${name}`);
      for (const alias of icon.aliases?.names ?? []) {
        regular.add(`fa-${alias}`);
      }
    }
  }
  return regular;
}

function* walk(directory) {
  for (const entry of readdirSync(directory)) {
    const path = join(directory, entry);
    if (statSync(path).isDirectory()) {
      yield* walk(path);
    } else if (sources.has(extname(path)) && !path.endsWith('.spec.ts')) {
      yield path;
    }
  }
}

const known = selectors();
const regular = regularIcons();
const styles = new Set(['fa-solid', 'fa-regular']);
const problems = [];

for (const path of walk(join(root, 'src'))) {
  const text = readFileSync(path, 'utf8');
  const where = relative(root, path);
  for (const match of text.matchAll(iconPattern)) {
    if (!known.has(match[0])) {
      problems.push(`${where}: ${match[0]} is not in Font Awesome Free`);
    }
  }
  for (const match of text.matchAll(quoted)) {
    const tokens = match[2].split(/\s+/).filter((token) => token.startsWith('fa-'));
    if (!tokens.includes('fa-regular')) {
      continue;
    }
    for (const token of tokens) {
      if (!styles.has(token) && known.has(token) && !regular.has(token) && token !== 'fa-spin') {
        problems.push(`${where}: ${token} has no regular style in Font Awesome Free; use fa-solid`);
      }
    }
  }
}

if (problems.length > 0) {
  console.error([...new Set(problems)].join('\n'));
  process.exit(1);
}
console.log('Every icon is in Font Awesome Free.');
