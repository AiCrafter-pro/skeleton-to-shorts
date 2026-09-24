"""설치 점검: 필수 준비물이 다 있는지 확인한다. 키·토큰 값은 출력하지 않는다.
사용: python check_setup.py"""
import importlib, os, shutil, subprocess, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "app"))
import config  # noqa: E402

ok_all = True


def row(ok, name, detail=""):
    global ok_all
    ok_all &= ok
    print(f"  [{'OK' if ok else '없음'}] {name}" + (f" — {detail}" if detail else ""))


print("뼈대부터 짓는다 — 설치 점검\n")

row(sys.version_info >= (3, 10), "Python 3.10+", sys.version.split()[0])
for mod in ("anthropic", "pydantic"):
    try:
        importlib.import_module(mod); row(True, f"파이썬 패키지 {mod}")
    except ImportError:
        row(False, f"파이썬 패키지 {mod}", "pip install -r requirements.txt")

row(bool(shutil.which("ffmpeg")) and bool(shutil.which("ffprobe")), "ffmpeg / ffprobe", "PATH에서 찾음" if shutil.which("ffmpeg") else "설치 후 PATH에 추가")

row(bool(config.ANTHROPIC_API_KEY), "ANTHROPIC_API_KEY (.env)", "설정됨(값은 표시하지 않음)" if config.ANTHROPIC_API_KEY else ".env.example → .env 복사 후 본인 키 입력")
row(True, "Claude 모델", config.CLAUDE_MODEL)

hf = bool(config.HIGGSFIELD_TOKEN)
if not hf and shutil.which("higgsfield"):
    try:
        out = subprocess.run("higgsfield auth token", capture_output=True, text=True, shell=True, timeout=30).stdout.strip()
        hf = bool(out)
    except Exception:
        hf = False
row(hf, "Higgsfield 인증", "CLI 로그인 확인(토큰은 표시하지 않음)" if hf else "Higgsfield CLI 설치 후 `higgsfield auth login`")

row(bool(config.BLENDER_PATH) and os.path.exists(config.BLENDER_PATH), "Blender 5.2+", config.BLENDER_PATH or ".env 의 BLENDER_PATH 지정")

gpu = shutil.which("nvidia-smi")
if gpu:
    try:
        name = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"], capture_output=True, text=True, timeout=5).stdout.strip()
        print(f"  [참고] GPU — {name} (1080p 렌더에 VRAM 약 6GB 사용)")
    except Exception:
        pass
else:
    print("  [참고] NVIDIA GPU를 못 찾음 — 렌더가 CPU로 매우 느릴 수 있음(720p 미리보기 품질 권장)")

print("\n" + ("모두 준비됨 → run.cmd(Windows) 또는 ./run.sh" if ok_all else "위 '없음' 항목을 채운 뒤 다시 실행하세요. README의 '필수 준비물' 참고"))
sys.exit(0 if ok_all else 1)
