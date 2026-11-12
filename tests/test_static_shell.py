import json
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"


def png_size(p):
    d = p.read_bytes()
    assert d[:8] == b"\x89PNG\r\n\x1a\n"
    return int.from_bytes(d[16:20], "big"), int.from_bytes(d[20:24], "big")


def test_manifest_icons_exist_with_declared_sizes():
    m = json.loads((STATIC / "manifest.webmanifest").read_text())
    assert m["background_color"] and m["theme_color"]
    pngs = [i for i in m["icons"] if i["type"] == "image/png"]
    assert {i["purpose"] for i in pngs} == {"any", "maskable"}
    for i in pngs:
        w, h = (int(x) for x in i["sizes"].split("x"))
        assert png_size(STATIC / i["src"].lstrip("/")) == (w, h)


def test_index_head_and_splash():
    html = (STATIC / "index.html").read_text()
    assert 'rel="apple-touch-icon"' in html and "apple-mobile-web-app-capable" in html
    assert "apple-mobile-web-app-status-bar-style" in html
    assert html.count('name="theme-color"') == 2 and "prefers-color-scheme: dark" in html
    assert 'id="splash"' in html
    assert png_size(STATIC / "apple-touch-icon.png") == (180, 180)


def test_service_worker_shell_lists_new_files_and_exists():
    sw = (STATIC / "sw.js").read_text()
    shell = re.search(r"SHELL = \[(.*?)\];", sw, re.S).group(1)
    listed = re.findall(r"'/([^']*)'", shell)
    for name in ("icon-192.png", "icon-512.png", "icon-maskable-512.png", "apple-touch-icon.png"):
        assert name in listed
    for name in listed:
        assert name == "" or (STATIC / name).is_file(), name


def test_service_worker_waits_for_the_update_banner():
    sw = (STATIC / "sw.js").read_text()
    install = re.search(r"addEventListener\('install'.*?\n\}\);", sw, re.S).group(0)
    assert "skipWaiting" not in install
    assert "SKIP_WAITING" in sw and "self.skipWaiting()" in sw
    assert "macrolog-shell-v46" in sw and "'/js/update.js'" in sw
    assert (STATIC / "js" / "update.js").is_file()
