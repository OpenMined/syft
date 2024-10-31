import os
from http.server import HTTPServer, SimpleHTTPRequestHandler


class AcmeChallengeHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        # Serve files from the ".well-known/acme-challenge/" folder if requested
        if self.path.startswith("/.well-known/acme-challenge/"):
            # Construct the full file path relative to the current working directory
            requested_file = os.path.join(os.getcwd(), self.path[1:])  # Remove leading '/'
            print("Requested file:", requested_file)

            # Check if the file exists
            if os.path.exists(requested_file) and os.path.isfile(requested_file):
                # Serve the file manually
                try:
                    with open(requested_file, "rb") as f:
                        self.send_response(200)
                        self.send_header("Content-type", "text/plain")
                        self.end_headers()
                        self.wfile.write(f.read())
                    return
                except IOError:
                    self.send_error(500, "Internal Server Error")
                    return
            else:
                self.send_error(404, "File not found")
                return
        elif self.path == "/" or self.path == "/index.html":
            # Serve index.html for the root path or explicit index.html request
            index_file = os.path.join(os.getcwd(), "index.html")
            print("Serving index.html:", index_file)

            if os.path.exists(index_file) and os.path.isfile(index_file):
                try:
                    with open(index_file, "rb") as f:
                        self.send_response(200)
                        self.send_header("Content-type", "text/html")
                        self.end_headers()
                        self.wfile.write(f.read())
                    return
                except IOError:
                    self.send_error(500, "Internal Server Error")
                    return
            else:
                self.send_error(404, "index.html not found")
                return
        else:
            # Redirect to /index.html if root path is picked
            if self.path == "/":
                self.send_response(302)
                self.send_header("Location", "/index.html")
                self.end_headers()
            else:
                self.send_error(404, "File not found")
            return


if __name__ == "__main__":
    PORT = 8080  # Port number to listen on
    server_address = ("", PORT)
    httpd = HTTPServer(server_address, AcmeChallengeHandler)
    print(f"Serving on port {PORT}")
    httpd.serve_forever()
