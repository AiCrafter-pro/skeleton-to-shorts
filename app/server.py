"""뼈대부터 짓는다 — 로컬 서버. 기본 http://127.0.0.1:8932 (.env 의 HOST·PORT)"""
import json, mimetypes, os, platform, re, socket, subprocess, sys
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, unquote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config, pipeline, hf_mcp

ROOT = pipeline.ROOT
WEB = os.path.join(ROOT, "web")
_voices = None


def voices():
    global _voices
    if _voices is None:
        _voices = [{"id": v["voice_id"], "name": v["name"], "gender": v["gender"], "preview": v.get("preview_url")}
                   for v in hf_mcp.call("list_voices", {})["voices"]]
    return _voices


def gpu_info():
    """nvidia-smi로 GPU 이름·VRAM 사용량(MiB). NVIDIA가 아니면 None."""
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,memory.used,utilization.gpu", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5).stdout.strip().splitlines()[0]
        name, tot, used, util = [x.strip() for x in out.split(",")]
        return {"name": name, "total": int(tot), "used": int(used), "util": int(util)}
    except Exception:
        return None


def focus_blender():
    """Blender 창을 맨 앞으로(Windows 전용, 다른 OS는 건너뜀)."""
    if platform.system() != "Windows":
        return False
    try:
        import ctypes
        from ctypes import wintypes
        u = ctypes.windll.user32; found = []
        cb = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def enum(h, _):
            n = u.GetWindowTextLengthW(h)
            if n and u.IsWindowVisible(h):
                b = ctypes.create_unicode_buffer(n + 1); u.GetWindowTextW(h, b, n + 1)
                if "Blender" in b.value and "Chromium" not in b.value and "Chrome" not in b.value: found.append(h)
            return True
        u.EnumWindows(cb(enum), 0)
        if not found: return False
        h = found[0]
        u.keybd_event(0x12, 0, 0, 0); u.keybd_event(0x12, 0, 2, 0)  # Alt 눌렀다 떼기: 포커스 전환 허용
        if u.IsIconic(h): u.ShowWindow(h, 9)
        u.SetForegroundWindow(h)
        return True
    except Exception:
        return False


def blender_live(j):
    """열려 있는 Blender(Higgsfield 애드온 소켓 127.0.0.1:9876)에 새 씬으로 건설 장면을 만들고 재생한다."""
    title = (j.s["assets"].get("plan") or {}).get("title") or j.s["topic"]
    args = {"--glb": j.path("model.glb"), "--live": "1", "--quality": "final",
            "--scene": "건축쇼츠_" + title.replace(" ", ""), "--shading": "MATERIAL", "--play": "1",
            "--kind": (j.s["assets"].get("plan") or {}).get("kind", "building")}
    with open(os.path.join(pipeline.APP, "blender_build.py"), encoding="utf-8") as f:
        code = "ARGS = " + json.dumps(args, ensure_ascii=False) + "\n" + f.read()
    s = socket.create_connection(("127.0.0.1", config.BLENDER_ADDON_PORT), timeout=300)
    s.sendall((json.dumps({"type": "execute", "code": code, "strict_json": False}) + "\0").encode("utf-8"))
    buf = b""
    while b"\0" not in buf:
        c = s.recv(65536)
        if not c:
            break
        buf += c
    s.close()
    r = json.loads(buf.split(b"\0")[0])
    if r.get("status") != "ok":
        raise RuntimeError(str(r.get("message"))[:300])
    out = r.get("result") or {}
    out["focused"] = focus_blender()
    return out


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code); self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b))); self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(b)

    def _file(self, path):
        if not os.path.isfile(path):
            return self._json({"error": "없음"}, 404)
        size = os.path.getsize(path); ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if path.endswith(".glb"): ctype = "model/gltf-binary"
        if path.endswith(".html"): ctype = "text/html; charset=utf-8"
        rng = self.headers.get("Range"); start, end = 0, size - 1
        m = re.match(r"bytes=(\d*)-(\d*)", rng or "")
        if m:
            if m.group(1): start = int(m.group(1))
            if m.group(2): end = min(int(m.group(2)), size - 1)
            self.send_response(206); self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", ctype); self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1)); self.send_header("Cache-Control", "no-store"); self.end_headers()
        with open(path, "rb") as f:
            f.seek(start); left = end - start + 1
            while left > 0:
                b = f.read(min(1 << 20, left))
                if not b: break
                try:
                    self.wfile.write(b)
                except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
                    return
                left -= len(b)

    def _job(self, jid):
        j = pipeline.Job(jid)
        return j if j.s else None

    def do_GET(self):
        p = unquote(urlparse(self.path).path)
        if p in ("/", "/index.html"):
            return self._file(os.path.join(WEB, "index.html"))
        if p == "/api/voices":
            try:
                return self._json(voices())
            except Exception as e:
                return self._json({"error": str(e)}, 500)
        if p == "/api/jobs":
            return self._json(pipeline.list_jobs())
        if p == "/api/system":
            return self._json({"gpu": gpu_info(), "rendering": any(pipeline.Job(k).s["steps"]["render"]["status"] == "running" for k in list(pipeline.RUNNING))})
        m = re.match(r"^/api/jobs/([\w\-]+)$", p)
        if m:
            j = self._job(m.group(1))
            if not j: return self._json({"error": "없음"}, 404)
            s = dict(j.s); s["running"] = j.id in pipeline.RUNNING
            return self._json(s)
        m = re.match(r"^/files/([\w\-]+)/([\w\-.]+)$", p)
        if m:
            return self._file(os.path.join(pipeline.JOBS, m.group(1), m.group(2)))
        self._json({"error": "없음"}, 404)

    def do_POST(self):
        p = urlparse(self.path).path
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads((self.rfile.read(n) or b"{}").decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return self._json({"error": "요청 본문은 UTF-8 JSON이어야 합니다"}, 400)
        if p == "/api/jobs":
            topic = (body.get("topic") or "").strip()[:40]
            if not topic: return self._json({"error": "주제를 입력하세요"}, 400)
            try:
                vid = body.get("voice_id") or voices()[0]["id"]
            except Exception as e:
                return self._json({"error": f"Higgsfield 연결 실패: {e}"}, 500)
            j = pipeline.new_job(topic, vid, body.get("quality", "final"), body.get("bgm", "bright"), review=body.get("review", True))
            pipeline.start(j); return self._json({"id": j.id})
        m = re.match(r"^/api/jobs/([\w\-]+)/(\w+)$", p)
        if not m: return self._json({"error": "없음"}, 404)
        j, act = self._job(m.group(1)), m.group(2)
        if not j: return self._json({"error": "없음"}, 404)
        busy = j.id in pipeline.RUNNING
        try:
            if act == "approve":
                if busy: return self._json({"error": "이미 진행 중"}, 409)
                pipeline.approve(j, body); return self._json({"ok": True})
            if act == "replan":
                if busy: return self._json({"error": "이미 진행 중"}, 409)
                pipeline.replan(j); return self._json({"ok": True})
            if act == "resume":
                if busy: return self._json({"error": "이미 진행 중"}, 409)
                pipeline.start(j); return self._json({"ok": True})
            if act == "blender":
                if not os.path.exists(j.path("model.glb")): return self._json({"error": "3D 모델이 아직 없습니다"}, 400)
                return self._json(blender_live(j))
            if act == "folder":
                if platform.system() == "Windows": os.startfile(j.dir)
                else: subprocess.Popen(["open" if platform.system() == "Darwin" else "xdg-open", j.dir])
                return self._json({"ok": True})
        except ConnectionRefusedError:
            return self._json({"error": f"Blender가 열려 있지 않거나 Higgsfield Blender 애드온 연결({config.BLENDER_ADDON_PORT})이 꺼져 있습니다"}, 503)
        except Exception as e:
            return self._json({"error": str(e)[:400]}, 500)
        self._json({"error": "없음"}, 404)


if __name__ == "__main__":
    os.makedirs(pipeline.JOBS, exist_ok=True)
    print(f"뼈대부터 짓는다 → http://{config.HOST}:{config.PORT}", flush=True)
    ThreadingHTTPServer((config.HOST, config.PORT), H).serve_forever()
