"""Higgsfield MCP(https://mcp.higgsfield.ai/mcp) 최소 클라이언트.
인증 토큰은 로그인된 Higgsfield CLI(`higgsfield auth token`)에서 받아 메모리에만 둔다.
(.env 의 HIGGSFIELD_TOKEN 이 있으면 그 값을 쓴다.)"""
import json, subprocess, time, urllib.request, urllib.error, itertools

import config

URL = config.HIGGSFIELD_MCP_URL
_ids = itertools.count(1)
_tok = None


def _token():
    global _tok
    if _tok is None:
        if config.HIGGSFIELD_TOKEN:
            _tok = config.HIGGSFIELD_TOKEN
        else:
            out = subprocess.run("higgsfield auth token", capture_output=True, text=True, shell=True).stdout.strip()
            if not out:
                raise RuntimeError("Higgsfield 토큰을 못 받았습니다. Higgsfield CLI 설치 후 `higgsfield auth login` 으로 로그인하세요 (README '필수 준비물')")
            _tok = out.splitlines()[-1].strip()
    return _tok


def _post(body):
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), method="POST", headers={
        "Authorization": "Bearer " + _token(), "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream"})
    with urllib.request.urlopen(req, timeout=180) as r:
        txt = r.read().decode("utf-8")
    # SSE(event: message / data: {...}) 또는 순수 JSON
    for line in txt.splitlines():
        if line.startswith("data:"):
            return json.loads(line[5:].strip())
    return json.loads(txt)


def call(tool, args):
    """MCP 도구 호출. 결과 텍스트를 JSON으로 풀 수 있으면 dict로 돌려준다."""
    msg = _post({"jsonrpc": "2.0", "id": next(_ids), "method": "tools/call", "params": {"name": tool, "arguments": args}})
    if "error" in msg:
        raise RuntimeError(f"{tool}: {msg['error']}")
    res = msg["result"]
    if res.get("structuredContent"):
        return res["structuredContent"]
    texts = [c.get("text", "") for c in res.get("content", []) if c.get("type") == "text"]
    joined = "\n".join(texts)
    try:
        return json.loads(joined)
    except Exception:
        if res.get("isError"):
            raise RuntimeError(f"{tool}: {joined[:500]}")
        return {"text": joined}


def upload_file(path, content_type):
    """media_upload(presigned PUT) → media_confirm. media_id 반환."""
    import os
    name = os.path.basename(path)
    up = call("media_upload", {"filename": name, "content_type": content_type})
    u = (up.get("uploads") or [up])[0]
    with open(path, "rb") as f:
        data = f.read()
    req = urllib.request.Request(u["upload_url"], data=data, method="PUT", headers={"Content-Type": content_type})
    urllib.request.urlopen(req, timeout=300).read()
    typ = content_type.split("/")[0]
    call("media_confirm", {"type": typ if typ in ("image", "video", "audio") else "file", "media_id": u["media_id"]})
    return u["media_id"]


def wait_jobs(job_ids, timeout=1800, on_tick=None):
    """jobs_wait를 반복해 모두 끝날 때까지 기다린다. {job_id: result_url} 반환(실패는 None)."""
    t0 = time.time(); out = {}
    jobs = [{"index": i, "job_id": j} for i, j in enumerate(job_ids)]
    while time.time() - t0 < timeout:
        r = call("jobs_wait", {"jobs": jobs, "timeout_seconds": 15})
        for j in r.get("jobs", []):
            if j["status"] == "completed":
                out[j["job_id"]] = j.get("result_url")
            elif j["status"] in ("failed", "canceled", "nsfw", "error"):
                out[j["job_id"]] = None
        if on_tick:
            on_tick(r.get("summary", {}))
        if r.get("all_terminal"):
            return out
        time.sleep(max(1, r.get("poll_after_seconds", 5) - 15 if r.get("timed_out") else 2))
    raise TimeoutError("Higgsfield 작업 대기 시간 초과")
