import http.server, socketserver, os, sys, threading

ROOT = r"D:\TLGL\.scratch\webpreview"
os.chdir(ROOT)


class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def log_message(self, *a):
        pass


with socketserver.TCPServer(("127.0.0.1", 8792), H) as httpd:
    print("serving", ROOT, "on 8792", flush=True)
    httpd.serve_forever()
