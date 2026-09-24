"""렌더 영상 + 기획 + 내레이션 → 최종 쇼츠(자막·단계 표시·진행 막대·BGM)."""
import json, os, subprocess

APP = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(APP, "fonts")
SERIES = "뼈대부터 짓는다"


def dur_of(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                         capture_output=True, text=True).stdout.strip()
    return float(out or 0)


def ts(t):
    t = max(0, t); h = int(t // 3600); m = int(t % 3600 // 60); s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def esc(s):
    return s.replace("\\", "＼").replace("{", "(").replace("}", ")").replace("\n", " ")


def schedule(narr_files, stages, total):
    """내레이션 줄을 단계 시작에 맞춰 배치. 겹치면 뒤로 밀고, 끝을 넘으면 속도를 조금 올린다."""
    anchors = [0.3, stages["sketch"][0] + 2.2, stages["frame"][0] + 0.2, stages["model"][0] + 0.2, stages["real"][0] + 0.2, stages["real"][0] + 5.2]
    out, prev_end = [], 0
    for i, f in enumerate(narr_files):
        d = dur_of(f); start = max(anchors[min(i, len(anchors) - 1)], prev_end + 0.2)
        nxt = anchors[i + 1] if i + 1 < len(anchors) else total - 0.3
        room = max(1.0, (nxt if i + 1 < len(anchors) else total - 0.3) - start - 0.1)
        tempo = min(1.3, max(1.0, d / room))
        d2 = d / tempo
        out.append({"file": f, "start": round(start, 2), "dur": round(d2, 2), "tempo": round(tempo, 3)})
        prev_end = start + d2
    return out


def write_ass(path, plan, meta, sched, lines):
    W, H = 1080, 1920
    st = meta["stages"]; total = meta["dur"]
    keys = ["sketch", "frame", "model", "real"]
    labels = {s["key"]: s for s in plan["stages"]}
    ev = []
    E = lambda t0, t1, style, text: ev.append(f"Dialogue: 0,{ts(t0)},{ts(t1)},{style},,0,0,0,,{text}")
    # 상단: 시리즈·훅·제목
    E(0, total, "Series", SERIES)
    E(0.2, total, "Hook", "{\\fad(400,0)}" + esc(plan["hook"]))
    E(0.4, total, "Title", "{\\fad(500,0)}" + esc(plan["title"]))
    # 단계 번호·이름·설명 (하단 왼쪽)
    for n, k in enumerate(keys):
        t0 = st[k][0]; t1 = st[keys[n + 1]][0] if n < 3 else total
        s_ = labels.get(k, {"label": k, "caption": ""})
        E(t0, t1, "StageNum", "{\\an1\\pos(58,1652)\\fad(250,200)}" + f"0{n + 1}")
        E(t0, t1, "StageLabel", "{\\an1\\pos(214,1636)\\fad(250,200)}" + esc(s_["label"]))
        E(t0 + 0.25, t1, "StageCap", "{\\an7\\pos(62,1664)\\fad(300,200)}" + esc(s_["caption"]))
        # 4단계 탭: 현재 단계 강조
        for m, k2 in enumerate(keys):
            x = 60 + 240 * m + 120
            lab = esc(labels.get(k2, {"label": k2})["label"])
            if m == n:
                E(t0, t1, "TabOn", "{\\an5\\pos(%d,1742)}%s" % (x, lab))
            else:
                E(t0, t1, "TabOff", "{\\an5\\pos(%d,1742)}%s" % (x, lab))
    # 진행 막대 (배경 트랙 + \clip 애니메이션)
    bar = "m 0 0 l 960 0 960 10 0 10"
    E(0, total, "Track", "{\\an7\\pos(60,1782)\\p1}" + bar)
    ms = int(total * 1000)
    E(0, total, "Bar", "{\\an7\\pos(60,1782)\\clip(60,1770,61,1800)\\t(0,%d,\\clip(60,1770,1020,1800))\\p1}%s" % (ms, bar))
    # 내레이션 자막
    for i, (s_, text) in enumerate(zip(sched, lines)):
        if i >= len(plan["narration"]):
            continue  # 마지막 줄(엔딩)은 큰 글씨 Outro로만 보여 준다
        E(s_["start"], s_["start"] + s_["dur"] + 0.15, "Narr", esc(text))
    # 엔딩
    E(total - 2.6, total, "Outro", "{\\fad(400,0)}" + esc(plan.get("outro", "")))
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Series,Pretendard Bold,36,&H00FFFFFF,&H000000FF,&H40000000,&H00000000,0,0,0,0,100,100,5,0,1,4,0,7,60,60,70,1
Style: Hook,Pretendard ExtraBold,52,&H0030D8FF,&H000000FF,&H00101010,&H00000000,0,0,0,0,100,100,1,0,1,5,0,8,60,60,146,1
Style: Title,Pretendard Black,116,&H00FFFFFF,&H000000FF,&H00141414,&H64000000,0,0,0,0,100,100,1,0,1,7,3,8,50,50,212,1
Style: StageNum,Pretendard Black,124,&H003A3AE0,&H000000FF,&H00FFFFFF,&H00000000,0,0,0,0,100,100,0,0,1,5,0,1,60,60,296,1
Style: StageLabel,Pretendard ExtraBold,66,&H00FFFFFF,&H000000FF,&H00141414,&H00000000,0,0,0,0,100,100,1,0,1,6,0,1,222,60,316,1
Style: StageCap,Pretendard ExtraBold,44,&H00FFFFFF,&H000000FF,&H00101010,&H00000000,0,0,0,0,100,100,0,0,1,6,0,1,64,60,248,1
Style: TabOn,Pretendard ExtraBold,36,&H0060D0FF,&H000000FF,&H00141414,&H00000000,0,0,0,0,100,100,1,0,1,4,0,5,0,0,0,1
Style: TabOff,Pretendard Bold,32,&H28FFFFFF,&H000000FF,&H60101010,&H00000000,0,0,0,0,100,100,1,0,1,4,0,5,0,0,0,1
Style: Track,Pretendard Bold,20,&HA0000000,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1
Style: Bar,Pretendard Bold,20,&H0060D0FF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1
Style: Narr,Pretendard ExtraBold,58,&H00FFFFFF,&H000000FF,&H00000000,&H40000000,0,0,0,0,100,100,0,0,3,22,0,2,80,80,560,1
Style: Outro,Pretendard ExtraBold,74,&H00FFFFFF,&H000000FF,&H00141414,&H64000000,0,0,0,0,100,100,1,0,1,6,3,5,60,60,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    with open(path, "w", encoding="utf-8-sig") as f:
        f.write(head + "\n".join(ev) + "\n")


def compose(job_dir, plan, meta, narr_files, music_path, log=print):
    total = meta["dur"]
    lines = plan["narration"] + [plan.get("outro", "")]
    lines = lines[:len(narr_files)]
    sched = schedule(narr_files, meta["stages"], total)
    json.dump(sched, open(os.path.join(job_dir, "narration_schedule.json"), "w"), indent=1)
    write_ass(os.path.join(job_dir, "subs.ass"), plan, meta, sched, lines)
    bgm = music_path
    # 오디오 필터: 내레이션 배치 + BGM 더킹
    inputs = ["-i", "render.mp4", "-i", bgm]
    parts, labels = [], []
    for i, s_ in enumerate(sched):
        inputs += ["-i", s_["file"]]
        d = int(s_["start"] * 1000)
        parts.append(f"[{i + 2}:a]aresample=48000,atempo={s_['tempo']},adelay={d}|{d},apad=whole_dur={total}[n{i}]")
        labels.append(f"[n{i}]")
    parts.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0,volume=1.3,asplit=2[narr][key]")
    parts.append(f"[1:a]aresample=48000,atrim=0:{total},volume=0.42,afade=t=in:d=0.6,afade=t=out:st={total - 2.5}:d=2.5[bgm]")
    parts.append("[bgm][key]sidechaincompress=threshold=0.03:ratio=6:attack=20:release=400[duck]")
    parts.append(f"[duck][narr]amix=inputs=2:normalize=0,alimiter=limit=0.89,volume=0.8[aout]")
    fontdir = os.path.relpath(FONT_DIR, job_dir).replace("\\", "/")
    vf = f"unsharp=5:5:0.55:5:5:0.0,subtitles=subs.ass:fontsdir={fontdir},format=yuv420p"
    cmd = ["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", ";".join(parts) + f";[0:v]{vf}[vout]",
           "-map", "[vout]", "-map", "[aout]", "-c:v", "libx264", "-crf", "16", "-preset", "slow", "-profile:v", "high", "-r", str(meta["fps"]),
           "-c:a", "aac", "-b:a", "192k", "-t", str(total), "-movflags", "+faststart", "final.mp4"]
    log("합성: 자막·단계 표시·진행 막대·내레이션·BGM")
    r = subprocess.run(cmd, cwd=job_dir, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg 합성 실패: " + r.stderr[-800:])
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(total - 1.0), "-i", "final.mp4", "-frames:v", "1", "-vf", "scale=540:-1", "poster.jpg"], cwd=job_dir)
    return os.path.join(job_dir, "final.mp4")
