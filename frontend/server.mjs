import http from 'node:http';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.dirname(fileURLToPath(import.meta.url));
const publicRoot = path.join(root, 'public');
const types = {
  '.css': 'text/css; charset=utf-8',
  '.html': 'text/html; charset=utf-8',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.svg': 'image/svg+xml',
};

function resolveRequest(pathname) {
  if (pathname === '/') return path.join(root, 'index.html');
  if (pathname.startsWith('/src/')) return path.resolve(root, `.${pathname}`);
  return path.resolve(publicRoot, `.${pathname}`);
}

const server = http.createServer(async (request, response) => {
  try {
    const pathname = decodeURIComponent(new URL(request.url, 'http://localhost').pathname);
    const filename = resolveRequest(pathname);
    const allowed = filename === path.join(root, 'index.html') || filename.startsWith(`${root}${path.sep}src${path.sep}`) || filename.startsWith(`${publicRoot}${path.sep}`);
    if (!allowed) {
      response.writeHead(403).end();
      return;
    }
    const body = await readFile(filename);
    response.writeHead(200, {
      'Cache-Control': 'no-store',
      'Content-Type': types[path.extname(filename)] ?? 'application/octet-stream',
      'X-Content-Type-Options': 'nosniff',
    });
    response.end(body);
  } catch {
    response.writeHead(404).end('Not found');
  }
});

server.listen(4173, '127.0.0.1', () => console.log('http://127.0.0.1:4173'));
