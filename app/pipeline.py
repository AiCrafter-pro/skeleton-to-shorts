"""주제 → 쇼츠 파이프라인. 단계별 결과를 jobs/<id>/ 에 저장하고 state.json으로 진행 상황을 공개한다.
유료 단계(이미지·3D·음성)는 결과 파일이 있으면 건너뛴다(재결제 방지). 자동 유료 재시도는 하지 않는다."""
import json, os, re, subprocess, threading, time, traceback, urllib.request, uuid
from concurrent.futures import ThreadPoolExecutor

import config, hf_mcp, planner, compose

APP = config.APP
ROOT = config.ROOT
JOBS = config.JOBS_DIR
ISOLATED = os.path.join(ROOT, ".blender_isolated")  # 사용자 Blender 설정·애드온을 건드리지 않도록 분리된 설정 폴더
STEPS = [("plan", "기획", "Claude Opus 5.5"), ("image", "완성 이미지", "Higgsfield · GPT Image 2.5"),
         ("model3d", "3D 모델", "Higgsfield · image_to_3d"), ("voice", "내레이션", "Higgsfield · TTS"),
         ("music", "배경음악", "Higgsfield · Sonilo Music"),
         ("render", "건설 애니메이션", "Blender"), ("compose", "합성", "ffmpeg")]
COST = {"image": 2.75, "model3d": 30.0, "voice": 0.15 * 6, "music": 1.88}
MUSIC_DEFAULT = "Uplifting cinematic score for a 30-second construction timelapse: soft start, steady rhythmic build, rising momentum, triumphant finale, no vocals"
_lock = threading.Lock()
RUNNING = {}


class Job:
    def __init__(self, jid):
        self.id = jid; self.dir = os.path.join(JOBS, jid); os.makedirs(self.dir, exist_ok=True)
        p = os.path.join(self.dir, "state.json")
        self.s = None
        for i in range(20):  # 저장과 겹치면 잠깐 뒤 다시 읽기
            try:
                if os.path.exists(p):
                    with open(p, encoding="utf-8") as f:
                        self.s = json.load(f)
                break
            except (PermissionError, json.JSONDecodeError):
                time.sleep(0.05)
        if self.s:  # 예전 작업에 새 단계 추가
            for k, n, b in STEPS:
                self.s["steps"].setdefault(k, {"key": k, "name": n, "by": b, "status": "pending"})
            self.s["steps"] = {k: self.s["steps"][k] for k, _, _ in STEPS}

    def save(self):
        with _lock:
            tmp = os.path.join(self.dir, "state.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.s, f, ensure_ascii=False, indent=1)
            # Windows: UI가 state.json을 읽는 순간에는 교체가 막힌다(WinError 5) → 잠깐 기다렸다 재시도
            for i in range(40):
                try:
                    os.replace(tmp, os.path.join(self.dir, "state.json")); return
                except PermissionError:
                    time.sleep(0.05)
            raise RuntimeError("상태 파일 저장 실패(다른 프로그램이 state.json을 잡고 있음)")

    def log(self, msg):
        self.s["log"].append([time.strftime("%H:%M:%S"), msg]); self.s["log"] = self.s["log"][-200:]; self.save()

    def step(self, key, **kw):
        st = self.s["steps"][key]; st.update(kw)
        if kw.get("status") == "running" and not st.get("t0"): st["t0"] = time.time()
        if kw.get("status") in ("done", "error"): st["t1"] = time.time()
        self.save()

    def path(self, name):
        return os.path.join(self.dir, name)


def new_job(topic, voice_id, quality="final", bgm="bright", review=True):
    jid = time.strftime("%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
    j = Job(jid)
    j.s = {"id": jid, "topic": topic, "voice_id": voice_id, "quality": quality, "bgm": bgm, "status": "queued",
           "created": time.time(), "credits_est": sum(COST.values()), "credits_used": 0.0,
           "steps": {k: {"key": k, "name": n, "by": b, "status": "pending"} for k, n, b in STEPS},
           "assets": {}, "log": [], "error": None, "review": review, "approved": not review}
    j.save(); return j


def _download(url, path):
    req = urllib.request.Request(url, headers={"User-Agent": "shorts-builder/1.0"})
    with urllib.request.urlopen(req, timeout=600) as r, open(path, "wb") as f:
        while True:
            b = r.read(1 << 20)
            if not b: break
            f.write(b)


def _first_job_id(res):
    r = res.get("results") or res.get("jobs") or []
    if not r: raise RuntimeError("Higgsfield 응답에 작업 ID가 없음: " + json.dumps(res, ensure_ascii=False)[:300])
    return r[0]["id"] if "id" in r[0] else r[0]["job_id"]


def run(j: Job):
    RUNNING[j.id] = True
    j.s["status"] = "running"; j.s["error"] = None; j.save()
    try:
        # 1. 기획
        if not os.path.exists(j.path("plan.json")):
            j.step("plan", status="running"); j.log(f"Claude Opus 5.5에 '{j.s['topic']}' 기획 요청")
            plan = planner.make_plan(j.s["topic"])
            json.dump(plan, open(j.path("plan.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        plan = json.load(open(j.path("plan.json"), encoding="utf-8"))
        j.s["assets"]["plan"] = plan; j.step("plan", status="done", note=plan["title"])
        if j.s.get("review") and not j.s.get("approved"):
            j.s["status"] = "review"; j.log("기획안 검토 대기 — 확인 후 '이대로 짓기'를 누르세요"); j.save()
            return

        # 2. 완성 이미지
        if not os.path.exists(j.path("image.png")):
            j.step("image", status="running"); j.log("GPT Image 2.5로 완성 이미지 생성 (2.75크레딧)")
            res = hf_mcp.call("generate_image", {"params": {"model": "gpt_image_2_5", "aspect_ratio": "1:1", "resolution": "2k", "quality": "high", "count": 1, "prompt": plan["image_prompt"]}})
            jid = _first_job_id(res); j.s["assets"]["image_job"] = jid; j.save()
            urls = hf_mcp.wait_jobs([jid], timeout=900)
            if not urls.get(jid): raise RuntimeError("이미지 생성 실패(재시도는 직접 눌러야 함)")
            _download(urls[jid], j.path("image.png")); j.s["credits_used"] += COST["image"]
        j.s["assets"]["image"] = "image.png"; j.step("image", status="done")

        # 3·4. 3D 모델과 내레이션을 동시에
        def do_3d():
            if os.path.exists(j.path("model.glb")): return
            j.step("model3d", status="running"); j.log("image_to_3d로 텍스처 3D 모델 생성 (30크레딧, 약 5~15분)")
            res = hf_mcp.call("generate_3d", {"params": {"model": "image_to_3d", "should_texture": True, "enable_pbr": True, "target_polycount": 200000, "symmetry_mode": "auto", "medias": [{"value": j.s["assets"]["image_job"], "role": "image"}]}})
            jid = _first_job_id(res); j.s["assets"]["model_job"] = jid; j.save()
            t0 = time.time()
            urls = hf_mcp.wait_jobs([jid], timeout=2400, on_tick=lambda s: j.step("model3d", note=f"생성 중 {int(time.time() - t0)}초"))
            if not urls.get(jid): raise RuntimeError("3D 생성 실패(재시도는 직접 눌러야 함)")
            _download(urls[jid], j.path("model.glb")); j.s["credits_used"] += COST["model3d"]

        def do_voice():
            lines = plan["narration"] + [plan["outro"]]
            if all(os.path.exists(j.path(f"narr_{i}.mp3")) for i in range(len(lines))): return
            j.step("voice", status="running"); j.log(f"내레이션 {len(lines)}줄 음성 생성 (약 0.9크레딧)")
            jids = []
            for i, text in enumerate(lines):
                if os.path.exists(j.path(f"narr_{i}.mp3")): jids.append(None); continue
                res = hf_mcp.call("generate_audio", {"params": {"model": "text2speech_v2", "variant": "elevenlabs", "voice_type": "preset", "voice_id": j.s["voice_id"], "prompt": text}})
                jids.append(_first_job_id(res))
            urls = hf_mcp.wait_jobs([x for x in jids if x], timeout=900)
            for i, jid in enumerate(jids):
                if jid:
                    if not urls.get(jid): raise RuntimeError(f"내레이션 {i + 1}번 생성 실패")
                    raw = j.path(f"narr_{i}.raw"); _download(urls[jid], raw)
                    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", raw, "-ac", "1", "-ar", "48000", "-b:a", "160k", j.path(f"narr_{i}.mp3")], check=True)
                    os.remove(raw); j.s["credits_used"] += 0.15
            j.save()

        def do_music():
            if os.path.exists(j.path("music.m4a")): return
            j.step("music", status="running"); j.log("Sonilo Music으로 30초 배경음악 생성 (1.88크레딧)")
            res = hf_mcp.call("generate_audio", {"params": {"model": "sonilo_music", "duration": 30, "prompt": plan.get("music_prompt") or MUSIC_DEFAULT}})
            jid = _first_job_id(res)
            urls = hf_mcp.wait_jobs([jid], timeout=900)
            if not urls.get(jid): raise RuntimeError("배경음악 생성 실패(재시도는 직접 눌러야 함)")
            _download(urls[jid], j.path("music.m4a")); j.s["credits_used"] += COST["music"]; j.save()

        if j.s["assets"].get("image_job") is None and os.path.exists(j.path("image.png")) and not os.path.exists(j.path("model.glb")):
            # 이미지 작업 ID를 잃은 경우: 업로드해서 사용
            j.s["assets"]["image_job"] = hf_mcp.upload_file(j.path("image.png"), "image/png")
        with ThreadPoolExecutor(3) as ex:
            f3, fv, fm = ex.submit(do_3d), ex.submit(do_voice), ex.submit(do_music)
            for key, f in (("model3d", f3), ("voice", fv), ("music", fm)):
                try:
                    f.result(); j.step(key, status="done", note="")
                except Exception as e:
                    j.step(key, status="error", note=str(e)); raise
        j.s["assets"]["model"] = "model.glb"; j.save()

        # 5. Blender 건설 애니메이션
        if not os.path.exists(j.path("render.mp4")):
            j.step("render", status="running", progress=0); j.log(f"Blender 렌더 시작 ({'1080×1920 30fps' if j.s['quality'] == 'final' else '720×1280 24fps 미리보기'})")
            if not config.BLENDER_PATH or not os.path.exists(config.BLENDER_PATH):
                raise RuntimeError("Blender를 찾지 못했습니다. Blender 5.2 이상 설치 후 .env 의 BLENDER_PATH 에 blender 실행 파일 경로를 넣으세요")
            env = dict(os.environ, BLENDER_USER_RESOURCES=ISOLATED)
            cmd = [config.BLENDER_PATH, "-b", "--factory-startup", "--python", os.path.join(APP, "blender_build.py"), "--",
                   "--glb", j.path("model.glb"), "--out", j.path("render.mp4"), "--quality", j.s["quality"], "--kind", plan.get("kind", "building")]
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", env=env)
            total = None; tail = []
            for line in p.stdout:
                tail = (tail + [line])[-30:]
                if line.startswith("BUILD_READY"):
                    total = json.loads(line.split(" ", 1)[1])["frames"]
                m = re.match(r"PROGRESS (\d+)", line) or re.match(r"Fra:(\d+)", line) or re.search(r"Append frame (\d+)", line)
                if m and total:
                    j.step("render", progress=round(100 * int(m.group(1)) / total, 1), note=f"{m.group(1)}/{total} 프레임")
            p.wait()
            if p.returncode != 0 or not os.path.exists(j.path("render.mp4")):
                raise RuntimeError("Blender 렌더 실패: " + "".join(tail)[-600:])
        j.s["assets"]["render"] = "render.mp4"; j.step("render", status="done", progress=100)

        # 6. 합성
        j.step("compose", status="running"); j.log("자막·단계 표시·내레이션·BGM 합성")
        meta = json.load(open(j.path("render_meta.json")))
        n = len(plan["narration"]) + 1
        compose.compose(j.dir, plan, meta, [j.path(f"narr_{i}.mp3") for i in range(n)], j.path("music.m4a"), log=j.log)
        j.s["assets"]["final"] = "final.mp4"; j.s["assets"]["poster"] = "poster.jpg"
        j.step("compose", status="done"); j.s["status"] = "done"; j.log("완성!")
    except Exception as e:
        for k, st in j.s["steps"].items():
            if st["status"] == "running": st["status"] = "error"; st["note"] = str(e)[:300]
        j.s["status"] = "error"; j.s["error"] = str(e)[:1200]; j.log("오류: " + str(e)[:400])
        traceback.print_exc()
    finally:
        j.save(); RUNNING.pop(j.id, None)


def start(j):
    th = threading.Thread(target=run, args=(j,), daemon=True); th.start(); return th


def list_jobs():
    out = []
    if not os.path.isdir(JOBS): return out
    for d in sorted(os.listdir(JOBS), reverse=True):
        p = os.path.join(JOBS, d, "state.json")
        if d.startswith("_") or not os.path.exists(p): continue
        s = Job(d).s
        if not s: continue
        out.append({k: s.get(k) for k in ("id", "topic", "status", "created", "credits_used")} | {"poster": s["assets"].get("poster"), "title": (s["assets"].get("plan") or {}).get("title")})
    return out


EDITABLE = ("title", "hook", "outro")


def approve(j, edits):
    """사용자가 고친 기획안을 반영하고 유료 제작을 시작한다."""
    plan = json.load(open(j.path("plan.json"), encoding="utf-8"))
    for k in EDITABLE:
        if isinstance(edits.get(k), str) and edits[k].strip(): plan[k] = edits[k].strip()[:40]
    if isinstance(edits.get("narration"), list) and len(edits["narration"]) == len(plan["narration"]):
        plan["narration"] = [str(x).strip()[:60] or plan["narration"][i] for i, x in enumerate(edits["narration"])]
    if isinstance(edits.get("stages"), list) and len(edits["stages"]) == 4:
        for st, e in zip(plan["stages"], edits["stages"]):
            if e.get("label"): st["label"] = str(e["label"]).strip()[:8]
            if e.get("caption"): st["caption"] = str(e["caption"]).strip()[:24]
    json.dump(plan, open(j.path("plan.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    j.s["assets"]["plan"] = plan; j.s["approved"] = True; j.s["status"] = "queued"
    j.log("기획안 승인 — 제작 시작"); j.save(); start(j)


def replan(j):
    """기획만 다시(Claude). 유료 단계 결과가 이미 있으면 거부."""
    if os.path.exists(j.path("image.png")): raise RuntimeError("이미 이미지가 만들어져 기획을 바꿀 수 없습니다")
    if os.path.exists(j.path("plan.json")): os.remove(j.path("plan.json"))
    j.s["approved"] = False; j.s["steps"]["plan"].update(status="pending", t0=None, t1=None, note="")
    j.save(); start(j)
