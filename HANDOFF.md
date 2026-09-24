# HANDOFF — 에이전트용 설치·명세 문서

이 문서 하나로 저장소를 설치·점검·수정할 수 있도록 썼습니다. **Claude Opus 5.5(Claude Code 등)** 가 읽고 사용자의 PC에 설치하는 것을 전제로 합니다. 사람은 [README](README.md)의 요약으로 충분합니다.

## 0. 에이전트 행동 규칙 (먼저 읽기)
1. **비밀 값을 절대 출력·커밋하지 않는다.** `ANTHROPIC_API_KEY`, Higgsfield 토큰은 사용자가 `.env`에 직접 넣게 안내한다. 키를 대신 받아 적어 주는 경우에도 화면·로그·커밋에 내용을 남기지 않는다.
2. **유료 작업은 사용자 확인 후에만.** 쇼츠 1편 = Higgsfield 약 35.53 크레딧 + Claude API 약 $0.04. 설치 점검에서 유료 생성을 돌리지 않는다. 실패 시 자동 유료 재시도 금지.
3. 공용 Blender에서 `bpy.ops.wm.read_factory_settings()` 나 `--factory-startup`으로 **사용자 설정을 초기화하지 않는다**. 이 저장소는 `BLENDER_USER_RESOURCES=.blender_isolated`로 분리해서 실행한다(과거에 사용자 애드온 패키지가 지워진 사고가 있었음).
4. 사용자가 조작하는 UI(브라우저)는 사용자가 쓴다. 에이전트는 설치·수정·점검을 맡는다.

## 1. 필수 준비물
| 항목 | 확인 명령 | 없을 때 |
|---|---|---|
| Python 3.10+ | `python --version` | python.org 설치 |
| 패키지 anthropic, pydantic | `pip install -r requirements.txt` | — |
| ffmpeg, ffprobe (PATH) | `ffmpeg -version` | Windows: `winget install Gyan.FFmpeg` · macOS: `brew install ffmpeg` · Linux: 패키지 관리자 |
| Node.js 18+ | `node --version` | nodejs.org |
| Higgsfield CLI + 로그인 | `higgsfield --version`, `higgsfield auth token`(출력 값은 사용자에게 보여주지 말 것) | `npm install -g @higgsfield/cli` → `higgsfield auth login`(브라우저 로그인, 사용자가 직접) → 필요하면 `higgsfield workspace set` |
| Blender 5.2+ | `app/config.py`가 자동 탐색 | blender.org 설치, 못 찾으면 `.env`의 `BLENDER_PATH` |
| Anthropic API 키 | `.env`에 `ANTHROPIC_API_KEY=` 값이 있는지만 확인 | 사용자가 console.anthropic.com에서 발급 |
| (권장) NVIDIA GPU 6GB+ | `nvidia-smi` | 없으면 UI에서 "빠른 미리보기 720p" 사용 |

**한 번에 점검:** `python check_setup.py` — 항목별 OK/없음을 출력하고, 키·토큰 값은 출력하지 않는다. 종료 코드 0이면 준비 완료.

## 2. 설치 순서
```bash
git clone https://github.com/AiCrafter-pro/skeleton-to-shorts.git && cd skeleton-to-shorts
pip install -r requirements.txt
cp .env.example .env            # 사용자가 ANTHROPIC_API_KEY 입력
npm install -g @higgsfield/cli && higgsfield auth login
python check_setup.py
# 실행
python -u app/server.py         # 또는 run.cmd / ./run.sh
# → http://127.0.0.1:8932
```

## 3. 설정 (`.env` → `app/config.py`)
| 변수 | 기본값 | 설명 |
|---|---|---|
| `ANTHROPIC_API_KEY` | (필수) | Claude API 키 |
| `CLAUDE_MODEL` | `claude-opus-5-5` | 기획 모델 |
| `BLENDER_PATH` | 자동 탐색 | Windows `C:\Program Files\Blender Foundation\Blender*\blender.exe`(C~H 드라이브), macOS `/Applications/Blender.app/...`, Linux `blender`/`/snap/bin/blender` |
| `HIGGSFIELD_TOKEN` | (비움) | 비우면 `higgsfield auth token`으로 받아 메모리에만 둔다 |
| `HIGGSFIELD_MCP_URL` | `https://mcp.higgsfield.ai/mcp` | |
| `HOST` / `PORT` | `127.0.0.1` / `8932` | 로컬 서버 |
| `BLENDER_ADDON_PORT` | `9876` | 선택 기능 "Blender 창에서 재생"의 Higgsfield Blender 애드온 소켓 |
| `JOBS_DIR` | `./jobs` | 결과 폴더 |

환경 변수가 이미 있으면 `.env`보다 우선한다.

## 4. 파일 지도
```
app/config.py        설정 로드, Blender 경로 탐색
app/server.py        표준 라이브러리 HTTP 서버 + API
app/pipeline.py      작업 상태·단계 실행·재개 (jobs/<id>/state.json)
app/planner.py       Claude 기획 (messages.parse + Pydantic Plan)
app/hf_mcp.py        Higgsfield MCP JSON-RPC 클라이언트 (tools/call, jobs_wait, media_upload)
app/blender_build.py GLB → 건설 애니메이션 (배치 렌더 / 열린 Blender 라이브 겸용)
app/compose.py       ASS 자막 + 내레이션 배치 + 음악 더킹 + x264
app/fonts/           Pretendard (SIL OFL)
web/index.html       단일 페이지 UI
check_setup.py       설치 점검
docs/ARCHITECTURE.md 상세 구조·Blender 연출·알려진 함정
```

## 5. 파이프라인 명세
| 단계 | 호출 | 입력 → 출력(`jobs/<id>/`) | 비용 |
|---|---|---|---|
| plan | Claude `CLAUDE_MODEL`, `output_config.effort=high`, 구조화 출력 `Plan` | 주제 → `plan.json` (title, hook, kind=building\|object, image_prompt, stages×4, narration×5, outro, music_prompt, fact_notes) | 약 $0.04 |
| image | MCP `generate_image` model `gpt_image_2_5`, 1:1, 2k, high | → `image.png` | 2.75 |
| model3d | MCP `generate_3d` model `image_to_3d`, 텍스처+PBR, 200k 폴리, 입력은 image의 job id | → `model.glb` | 30 |
| voice | MCP `generate_audio` `text2speech_v2` elevenlabs, 6줄 | → `narr_0..5.mp3` | 0.15×6 |
| music | MCP `generate_audio` `sonilo_music` 30초 | → `music.m4a` | 1.88 |
| render | Blender 배치 `blender_build.py -- --glb --out --quality final\|preview --kind` | → `render.mp4`, `render_meta.json` | 로컬 GPU |
| compose | ffmpeg | → `subs.ass`, `final.mp4`, `poster.jpg` | — |

- model3d·voice·music은 동시에 돈다. 각 유료 단계는 **결과 파일이 있으면 건너뛴다**(재결제 방지).
- `review=true`로 만들면 plan 후 `status=review`에서 멈추고 사용자 승인을 기다린다.
- Blender 진행률은 `render_post` 핸들러가 출력하는 `PROGRESS n N` 줄로 읽는다.

## 6. HTTP API (`app/server.py`)
| 메서드 · 경로 | 설명 |
|---|---|
| `GET /` | UI |
| `GET /api/jobs` | 작업 목록 |
| `POST /api/jobs` `{topic, voice_id?, quality: final\|preview, review: bool}` | 새 작업 시작 → `{id}` |
| `GET /api/jobs/<id>` | 상태(state.json + running) |
| `POST /api/jobs/<id>/approve` `{title?, hook?, outro?, narration?[5], stages?[4]}` | 기획안 수정·승인 → 유료 단계 시작 |
| `POST /api/jobs/<id>/replan` | 기획만 다시(이미지가 생기기 전만) |
| `POST /api/jobs/<id>/resume` | 실패 지점부터 이어서 |
| `POST /api/jobs/<id>/blender` | 열린 Blender에 라이브 건설 장면(애드온 필요) |
| `POST /api/jobs/<id>/folder` | 결과 폴더 열기 |
| `GET /api/voices` | Higgsfield 음성 목록 |
| `GET /api/system` | GPU·VRAM(nvidia-smi), 렌더 중 여부 |
| `GET /files/<id>/<파일>` | 결과 파일(Range 지원) |

요청 본문은 **UTF-8 JSON**만 받는다(Windows Git Bash의 curl은 한글을 CP949로 보내 깨질 수 있음).

## 7. 문제 해결
| 증상 | 원인 · 조치 |
|---|---|
| "ANTHROPIC_API_KEY가 없습니다" | `.env` 없음/빈 값 → `.env.example` 복사 후 입력 |
| "Claude API 키가 유효하지 않습니다" | 키 오타·폐기 → 새로 발급 |
| "Higgsfield 토큰을 못 받았습니다" | CLI 미설치·미로그인 → `higgsfield auth login` |
| Higgsfield 오류 / 크레딧 부족 | Higgsfield 계정 크레딧·작업공간 확인 (`higgsfield workspace list`는 잔액이 보이니 화면 공유 중엔 주의) |
| "Blender를 찾지 못했습니다" | `.env`의 `BLENDER_PATH`에 실행 파일 전체 경로 |
| 렌더가 매우 느림 | GPU 없음 또는 렌더 두 개 동시 실행(각각 약 2배) → 한 번에 하나, 또는 720p 미리보기 |
| Windows `WinError 5` (state.json) | UI가 읽는 순간 교체 충돌 → 코드가 재시도함. 계속되면 백신 실시간 검사 예외 |
| "Blender 창에서 재생" 503 | Blender가 안 열렸거나 Higgsfield Blender 애드온 소켓(9876) 꺼짐 — 선택 기능이라 무시 가능 |
| 자막 글꼴이 이상함 | `app/fonts/`의 Pretendard 파일 확인(ffmpeg `fontsdir`로 씀) |

## 8. 고치기 쉬운 곳
- 언어: `planner.py`의 `SYSTEM`·`Plan` 필드 설명(현재 한국어), 음성은 UI에서 선택
- 길이·단계 시간표: `blender_build.py`의 `DUR`, `T`
- 자막 스타일: `compose.py`의 ASS 스타일
- 다른 모델: `.env`의 `CLAUDE_MODEL`, `pipeline.py`의 MCP 파라미터
