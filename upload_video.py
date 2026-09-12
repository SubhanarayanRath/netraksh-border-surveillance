import urllib.request
import urllib.parse
import json

url = "http://localhost:8443/auth/token"
data = urllib.parse.urlencode({"username": "admin", "password": "admin"}).encode("utf-8")
req = urllib.request.Request(url, data=data)
req.add_header('Content-Type', 'application/x-www-form-urlencoded')
with urllib.request.urlopen(req) as response:
    resp = json.loads(response.read().decode())
    token = resp["access_token"]
print("Token:", token)

import os
boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
body = []
body.append(f"--{boundary}")
body.append('Content-Disposition: form-data; name="file"; filename="Fixed_overhead_surveillance_ca.mp4"')
body.append('Content-Type: video/mp4')
body.append('')
with open(r"C:\Users\hp\Downloads\Fixed_overhead_surveillance_ca.mp4", "rb") as f:
    file_content = f.read()

body_bytes = b"".join([
    (item + "\r\n").encode("utf-8") for item in body
])
body_bytes += file_content + b"\r\n"
body_bytes += f"--{boundary}--\r\n".encode("utf-8")

upload_url = "http://localhost:8443/demo/upload"
req = urllib.request.Request(upload_url, data=body_bytes)
req.add_header('Authorization', f'Bearer {token}')
req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')

with urllib.request.urlopen(req) as response:
    print(response.getcode())
    print(response.read().decode())
