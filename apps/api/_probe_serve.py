import http.server
import pathlib
import re
import socketserver
import threading
import urllib.request

ROOT = pathlib.Path("generated/projects/pmtest00001/out").resolve()
PREFIX = "/api/projects/abc/preview"


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == PREFIX or path == PREFIX + "/":
            self._serve("index.html")
            return
        if path.startswith(PREFIX + "/"):
            rel = path[len(PREFIX) + 1:]
            if rel.startswith("_next/"):
                rel = rel[len("_next/"):]
                self._serve("_next/" + rel)
                return
            self._serve(rel)
            return
        self.send_response(404)
        self.end_headers()
        self.wfile.write(b"not found")

    def _serve(self, rel):
        target = ROOT / rel
        if not target.is_file():
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"missing " + rel.encode())
            return
        body = target.read_bytes()
        if rel.endswith(".html"):
            body = re.sub(rb"/_next/", (PREFIX + "/_next/").encode(), body)
        ctype = "text/html" if rel.endswith(".html") else "application/javascript"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


httpd = socketserver.TCPServer(("127.0.0.1", 0), Handler)
port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()

for url in [f"http://127.0.0.1:{port}{PREFIX}/", f"http://127.0.0.1:{port}{PREFIX}/_next/static/chunks/main-app-73bc3a3b1626b08c.js"]:
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            data = r.read()
            print(f"{url} -> {r.status} {len(data)} bytes")
            if url.endswith("/"):
                refs = re.findall(rb"/api/projects/abc/preview/_next/[a-zA-Z0-9/._-]+", data)
                print("   rewritten refs:", len(refs), "sample:", refs[0] if refs else None)
    except Exception as e:
        print(f"{url} -> ERROR {e}")

httpd.shutdown()