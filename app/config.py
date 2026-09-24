"""설정 한 곳. 값은 저장소 루트의 `.env`(없으면 환경 변수)에서 읽는다.
키·토큰은 코드에 쓰지 않는다. `.env` 는 .gitignore 로 올라가지 않는다 — `.env.example` 을 복사해서 쓴다."""
import glob, os, platform, shutil

APP = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(APP)


def _load_env(path):
    if not os.path.exists(path):
        return
    for raw in open(path, encoding="utf-8"):
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and v and k not in os.environ:  # 이미 있는 환경 변수가 우선
            os.environ[k] = v


_load_env(os.path.join(ROOT, ".env"))

# ── Claude API (필수) ─────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5-5")

# ── Higgsfield (필수) ─────────────────────────────────────────────
# 기본: 로그인된 Higgsfield CLI(`higgsfield auth login`)에서 토큰을 받아 메모리에만 둔다.
# CLI 없이 쓰려면 HIGGSFIELD_TOKEN 에 직접 넣을 수 있다(권장하지 않음 — 만료되면 다시 넣어야 함).
HIGGSFIELD_MCP_URL = os.environ.get("HIGGSFIELD_MCP_URL", "https://mcp.higgsfield.ai/mcp")
HIGGSFIELD_TOKEN = os.environ.get("HIGGSFIELD_TOKEN", "")

# ── Blender (필수) ────────────────────────────────────────────────
def _find_blender():
    if os.environ.get("BLENDER_PATH"):
        return os.environ["BLENDER_PATH"]
    found = shutil.which("blender")
    if found:
        return found
    sysname = platform.system()
    pats = []
    if sysname == "Windows":
        for drive in "CDEFGH":
            pats += [f"{drive}:\\Program Files\\Blender Foundation\\Blender*\\blender.exe"]
    elif sysname == "Darwin":
        pats += ["/Applications/Blender.app/Contents/MacOS/Blender"]
    else:
        pats += ["/usr/bin/blender", "/snap/bin/blender", os.path.expanduser("~/blender*/blender")]
    hits = sorted(h for p in pats for h in glob.glob(p))
    return hits[-1] if hits else ""  # 여러 개면 가장 높은 버전 폴더


BLENDER_PATH = _find_blender()

# ── 로컬 서버 ─────────────────────────────────────────────────────
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8932"))
# 열려 있는 Blender의 Higgsfield 애드온 소켓(선택 기능 "Blender 창에서 재생")
BLENDER_ADDON_PORT = int(os.environ.get("BLENDER_ADDON_PORT", "9876"))

JOBS_DIR = os.environ.get("JOBS_DIR") or os.path.join(ROOT, "jobs")
