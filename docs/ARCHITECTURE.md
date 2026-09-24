# 뼈대부터 짓는다 — 구조 문서 (v1, 2026-09-24)

주제 한 줄 → 「스케치 → 뼈대 → 모형 → 완성」으로 지어지는 **30초 9:16 쇼츠**. 사용자는 브라우저 UI에서 주제를 넣고 버튼만 누른다.

## 1. 실행
- 설치·실행은 [README](../README.md), 에이전트용 상세 명세는 [HANDOFF.md](../HANDOFF.md)
- 설정은 저장소 루트 `.env`(`.env.example` 복사) → `app/config.py`가 읽는다. 키·경로를 코드에 쓰지 않는다.
- 「Blender 창에서 재생」은 선택 기능: **열린 Blender + Higgsfield Blender 애드온(소켓 기본 9876)** 필요

## 2. 흐름
```
[UI 주제 입력] → POST /api/jobs (review=false 기본: 끝까지 자동 / true: 기획안 검토 후 승인)
 ① 기획   planner.py   Claude API claude-opus-5-5, messages.parse(Pydantic), effort high
          → title, hook, kind(building|object), image_prompt, stages×4, narration×5, outro, music_prompt, fact_notes
 ② 이미지 Higgsfield MCP generate_image  gpt_image_2_5 1:1 2k high             2.75
 ③ 3D     Higgsfield MCP generate_3d     image_to_3d 텍스처+PBR 200k폴리 (②의 job_id를 그대로 입력)   30
 ④ 음성   Higgsfield MCP generate_audio  text2speech_v2 elevenlabs, 6줄          0.15×6
 ⑤ 음악   Higgsfield MCP generate_audio  sonilo_music 30초                       1.88
          (③④⑤ 동시 실행)
 ⑥ 렌더   blender_build.py (격리 Blender, 1080×1920 30fps 900프레임, EEVEE 64샘플 레이트레이싱)
 ⑦ 합성   compose.py (ffmpeg: 샤픈 + ASS 자막 + 내레이션 배치 + 음악 더킹, x264 CRF16 slow)
→ jobs/<id>/final.mp4 (+poster.jpg)
```
- Higgsfield **1편 35.53 크레딧**, Claude API 약 **$0.04**(Anthropic 별도).
- 시간(개발 PC 실측, RTX 2060 SUPER 8GB): 기획 20초 · 이미지 30초 · ③④⑤ 약 5분 · **렌더 약 14.5분(단독)** · 합성 30초 → 약 20~22분. **렌더 두 개가 동시에 돌면 각각 약 31분.**
- VRAM: 렌더 중 약 6.2GB/8GB(평소 4.8GB).

## 3. 파일
| 파일 | 역할 |
|---|---|
| `app/server.py` | 표준 라이브러리 HTTP 서버. `/api/jobs`, `/api/jobs/<id>/(approve|replan|resume|blender|folder)`, `/api/voices`, `/api/system`(nvidia-smi), `/files/<id>/<파일>`(Range 지원) |
| `app/pipeline.py` | 작업 상태(`jobs/<id>/state.json`)·단계 실행·재개. **유료 단계는 결과 파일이 있으면 건너뜀**, 자동 유료 재시도 없음 |
| `app/planner.py` | Claude 기획(구조화 출력). building/object 판별 규칙, 브랜드명 금지, 불확실한 수치 금지 |
| `app/hf_mcp.py` | Higgsfield MCP(https://mcp.higgsfield.ai/mcp) JSON-RPC 클라이언트. 토큰은 `higgsfield auth token`에서 받아 메모리에만 |
| `app/blender_build.py` | GLB → 건설 애니메이션. 배치 렌더와 라이브 모드(`ARGS`로 소켓 실행, 새 씬에서만 작업) 겸용 |
| `app/compose.py` | ASS 자막(Pretendard), 단계 탭·진행 막대, 내레이션 스케줄, 음악 더킹 |
| `web/index.html` | UI(다크/라이트, 자동/검토 모드, 확인 창, 진행률·남은 시간, GPU·VRAM 표시, 결과·Blender 재생·폴더) |
| `app/config.py` | `.env` 읽기, Blender 경로 자동 탐색, 포트·모델 설정 |
| `app/fonts/` | Pretendard SemiBold~Black(SIL OFL 1.1) |

## 4. Blender 연출 (`blender_build.py`)
- 모델 정규화: 가장 긴 변 10, 바닥 z=0, 중심 원점
- 시간표(초): intro 0–1.5 · sketch 1.5–8 · frame 8–15 · model 15–21 · real 21–30
- 드러냄 셰이더: 월드 Z < 문턱값만 보이고 경계에 빛나는 띠(키프레임 문턱값)
  - ① 스케치: 줄인 메시(약 3,500면) 와이어프레임 먹선
  - ② 뼈대: **building** = 레이캐스트 높이 격자 기둥·보(나무색) / **object** = 가로 단면 링 15개 + 세로 단면 6개를 곡선→튜브(파란 금속)
  - ③ 모형: 흰 점토 복제본, 골조는 위에서부터 해체
  - ④ 완성: **원본 한 개의 재질 안에서** 경계 아래 텍스처·위 점토(겹친 복제본은 표면 충돌로 새까매져서 폐기한 방식)
  - 복제본은 자기 단계에서만 렌더(hide_render 키프레임)
- 배경: 종이색 격자 → 21+3초부터 야경(하늘·바닥·태양 전환, 스포트 4개 업라이트)
- 카메라: 세로 센서, 대상 높이 0.54H 조준, 거리 max(2.05H, 2.7·max(W,D)), 135° 회전·살짝 접근
- 진행률: `render_post` 핸들러가 `PROGRESS n N`을 즉시 출력(Blender C 출력은 파이프에서 버퍼링돼 못 씀)

## 5. 알려진 함정
- **백그라운드 Blender에서 `read_factory_settings`/`--factory-startup` 금지 → 대신 `BLENDER_USER_RESOURCES=.blender_isolated`로 격리**(공용 설정 폴더의 Higgsfield Blender 애드온 패키지가 지워진 실제 사고가 있었음)
- 라이브 모드에서 `SystemExit` 금지(열린 Blender가 꺼질 수 있음). 재생은 꺼져 있을 때만 `animation_play`(토글이라 켜진 걸 끔)
- Windows: UI가 읽는 순간 `os.replace(state.tmp→state.json)`가 WinError 5 → 재시도(0.05초 × 40)
- Git Bash의 curl로 한글 JSON을 보내면 CP949로 깨짐 → 서버는 UTF-8만 받음(브라우저는 문제없음)
- Higgsfield CLI `generate cost image_to_3d`는 조건 규칙 검증 오류 → MCP로 호출
- `sonilo_music`은 모델 설명에 "게임 파이프라인 전용"이라 적혀 있으나 MCP로 생성됨(2026-09-24 확인)
- 3D 텍스처 해상도 한계로 창문 같은 잔디테일은 흐림(설정으로 완전히 해결 안 됨)

## 6. 결과 폴더(`jobs/<id>/`)
plan.json · image.png · model.glb · narr_0..5.mp3 · music.m4a · render.mp4 · render_meta.json · subs.ass · narration_schedule.json · final.mp4 · poster.jpg · state.json
