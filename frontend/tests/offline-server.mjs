import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { resolve, extname, sep } from 'node:path';

const root = resolve('dist');
const types = { '.js': 'text/javascript', '.css': 'text/css', '.html': 'text/html', '.svg': 'image/svg+xml' };
createServer(async (request, response) => {
  const url = new URL(request.url, 'http://127.0.0.1:15274');
  if (request.method !== 'GET' || url.pathname.startsWith('/api/')) {
    response.writeHead(404).end(); return;
  }
  const file = resolve(root, '.' + decodeURIComponent(url.pathname));
  if (file !== root && !file.startsWith(root + sep)) { response.writeHead(403).end(); return; }
  try {
    const target = extname(file) ? file : resolve(root, 'index.html');
    response.writeHead(200, { 'Content-Type': types[extname(target)] || 'application/octet-stream' });
    response.end(await readFile(target));
  } catch { response.writeHead(404).end(); }
}).listen(15274, '127.0.0.1');
