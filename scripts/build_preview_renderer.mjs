#!/usr/bin/env node
// Bundle the exact host renderer, never a substitute parser or the host's global CSS.
import { createRequire } from 'node:module';
import { readFile, writeFile, lstat, realpath } from 'node:fs/promises';
import { resolve, dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
const repo = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const [platformArg, outputArg] = process.argv.slice(2);
if (!platformArg || !outputArg) throw new Error('Usage: node scripts/build_preview_renderer.mjs PLATFORM_ROOT OWNED_PREVIEW_ROOT');
const platform = await realpath(platformArg), output = resolve(outputArg);
if (output !== await realpath(output) || (await lstat(output)).mode & 0o077) throw new Error('Private owned preview root required');
const manifest = JSON.parse(await readFile(join(output, 'manifest.json'), 'utf8'));
if (manifest.owner !== 'manufacturing-oem-preview-v1' || manifest.directory !== output || manifest.complete) throw new Error('New owned preview preparation required');
const assets = join(output, 'webui', 'dist');
if ((await lstat(assets)).isSymbolicLink() || await realpath(assets) !== assets) throw new Error('Owned output required');
const require = createRequire(join(repo, 'webui', 'package.json'));
const { build } = require('esbuild');
const source = join(platform, 'webui', 'src', 'manufacturingMarkdown.tsx');
const result = await build({
  stdin: { contents: `export { createManufacturingMarkdownRenderer } from ${JSON.stringify(source)};`, resolveDir: join(platform, 'webui'), sourcefile: 'preview-renderer-entry.ts', loader: 'ts' },
  bundle: true, write: false, format: 'iife', globalName: 'PreviewMarkdown', platform: 'browser', jsx: 'automatic', minify: true,
  define: { 'process.env.NODE_ENV': '"production"' }, metafile: true,
});
await writeFile(join(assets, 'preview-renderer.js'), result.outputFiles[0].contents, {flag:'wx',mode:0o600});
const styles = await readFile(join(platform, 'webui', 'src', 'styles.css'), 'utf8');
// Only renderer-owned selector lines; all receive an outer preview scope.
const article = styles.split('\n').filter(line => /^(\.article-markdown|\.article-table-scroll|\.mermaid-)/.test(line) && line.includes('{') && line.includes('}')).map(line => line.replace(/(^|,\s*)(\.[\w-]+)/g, '$1.preview-shell $2')).join('\n');
if (!article.includes('.article-markdown table') || !article.includes('.article-markdown pre')) throw new Error('Renderer article styles unavailable');
const base = `.preview-shell{margin:0;--ink:#182b42;--ink-soft:#4b5d72;--line:#cad5e1;--line-soft:#e0e6ed;--brand-bright:#2168bd}.preview-notice{padding:8px 16px;background:#fff3ce;color:#5e4613;font:14px/1.5 system-ui}.preview-shell .article-markdown{max-width:100%;padding:12px 0}.preview-shell .mermaid-diagram img{max-width:100%}\n`;
await writeFile(join(assets,'preview.css'), base+article+'\n@media(max-width:720px){.preview-shell .article-markdown{font-size:16px}.preview-shell .mermaid-diagram-trigger>img{max-height:68svh}}', {flag:'wx',mode:0o600});
const sha = value => createHash('sha256').update(value).digest('hex');
const inputs = {};
for (const file of Object.keys(result.metafile.inputs)) {
  if (file.endsWith('preview-renderer-entry.ts')) continue;
  const absolute = resolve(file);
  inputs[absolute] = sha(await readFile(absolute));
}
process.stdout.write(JSON.stringify({source, sha256:sha(await readFile(source)), stylesheet:join(platform,'webui','src','styles.css'), stylesheet_sha256:sha(styles), inputs}));
