"""Validate both include contexts with nginx itself, never reload a server."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest

TEMPLATES = Path(__file__).resolve().parents[1] / "nginx"


def test_nginx_combines_http_and_existing_frontend_server_contexts(tmp_path):
    nginx = shutil.which("nginx")
    if nginx is None:
        if os.environ.get("PROJECT1_REQUIRE_NGINX") == "1":
            pytest.fail("nginx binary is required for the deployment gate")
        pytest.skip("nginx is unavailable locally; CI requires the real syntax gate")
    (tmp_path / "mobile").mkdir()
    (tmp_path / "admin").mkdir()
    http = (TEMPLATES / "se-course-project1-http.conf").resolve()
    routes = (TEMPLATES / "se-course-project1-routes.conf").resolve()
    config = tmp_path / "nginx.conf"
    config.write_text(f'''pid "{tmp_path / 'nginx.pid'}";
error_log stderr;
events {{ worker_connections 64; }}
http {{
    access_log off;
    client_body_temp_path "{tmp_path / 'body'}";
    proxy_temp_path "{tmp_path / 'proxy'}";
    fastcgi_temp_path "{tmp_path / 'fastcgi'}";
    uwsgi_temp_path "{tmp_path / 'uwsgi'}";
    scgi_temp_path "{tmp_path / 'scgi'}";
    include "{http}";
    server {{
        listen 127.0.0.1:18081;
        server_name mobile.example.test;
        root "{tmp_path / 'mobile'}";
        location / {{ try_files $uri $uri/ /index.html; }}
        location = /sw.js {{ add_header Cache-Control no-cache; }}
        include "{routes}";
    }}
    server {{
        listen 127.0.0.1:18082;
        server_name admin.example.test;
        root "{tmp_path / 'admin'}";
        location / {{ try_files $uri $uri/ /index.html; }}
        include "{routes}";
    }}
}}
''')
    result = subprocess.run([nginx, "-t", "-p", str(tmp_path) + "/", "-c", str(config)],
                            capture_output=True, text=True, timeout=15, check=False)
    assert result.returncode == 0, result.stderr
