import { readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = dirname(fileURLToPath(import.meta.url));
const dist = join(root, 'dist');
const template = await readFile(join(root, 'src/index.template.html'), 'utf8');
const css = await readFile(join(dist, 'style.css'), 'utf8');
const modules = await Promise.all(['hex.js', 'bsl.js', 'serial.js', 'waveform.js', 'app.js'].map(name => readFile(join(dist, name), 'utf8')));
const js = modules.map(source => source.replace(/^import .*?;\s*$/gm, '').replace(/^export /gm, '')).join('\n');
if (js.includes('</script>')) throw new Error('内联脚本含有 </script>，无法安全生成单文件页面');
if (!template.includes('<!-- INLINE_STYLES -->') || !template.includes('<!-- INLINE_SCRIPTS -->')) throw new Error('HTML 模板缺少内联资源标记');
const html = template
  .replace('<!-- INLINE_STYLES -->', `<style>\n${css}\n</style>`)
  .replace('<!-- INLINE_SCRIPTS -->', `<script>\n(() => {\n'use strict';\n${js}\n})();\n</script>`);
await writeFile(join(dist, 'index.html'), html);
console.log('已生成可双击打开的 dist/index.html');
