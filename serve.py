#!/usr/bin/env python3
"""Local translator server - accessible from any device on the same network."""
import http.server
import socket
import os

PORT = 8090
DIR = os.path.dirname(os.path.abspath(__file__))

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

os.chdir(DIR)
handler = http.server.SimpleHTTPRequestHandler

class DualStackServer(http.server.HTTPServer):
    address_family = socket.AF_INET6

    def server_bind(self):
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        super().server_bind()

server = DualStackServer(("::", PORT), handler)

ip = get_local_ip()
print(f"\n  Translator is running!\n")
print(f"  Computer:  http://localhost:{PORT}")
print(f"  Phone:     http://{ip}:{PORT}")
print(f"\n  (Make sure phone and computer are on the same WiFi)\n")
print(f"  Press Ctrl+C to stop.\n")

try:
    server.serve_forever()
except KeyboardInterrupt:
    print("\nStopped.")
    server.server_close()
