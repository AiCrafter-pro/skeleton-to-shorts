"""주제 → 쇼츠 기획(제목·단계 자막·내레이션·이미지 프롬프트). Claude Opus 5.5 구조화 출력."""
from typing import List, Literal

import anthropic
from pydantic import BaseModel, Field

import config

MODEL = config.CLAUDE_MODEL


class Stage(BaseModel):
    key: Literal["sketch", "frame", "model", "real"]
    label: str = Field(description="화면에 뜨는 단계 이름, 한국어 2~5자 (예: 스케치, 골조, 모형, 완공)")
    caption: str = Field(description="단계 설명 한 줄, 한국어 18자 이내")


class Plan(BaseModel):
    title: str = Field(description="쇼츠 큰 제목, 한국어 12자 이내 (예: 오사카성 짓기)")
    hook: str = Field(description="제목 위 작은 훅 문구, 한국어 20자 이내")
    kind: Literal["building", "object"]
    image_prompt: str = Field(description="완성된 대상 1장을 만드는 영어 프롬프트")
    stages: List[Stage] = Field(min_length=4, max_length=4)
    narration: List[str] = Field(min_length=5, max_length=5,
                                 description="한국어 내레이션 5줄: [도입, 스케치, 골조, 모형, 완공]. 각 줄 35자 이내")
    outro: str = Field(description="마지막 화면 한 줄, 한국어 16자 이내")
    music_prompt: str = Field(description="30초 배경음악 생성용 영어 프롬프트: 장르·악기·분위기·전개(잔잔한 시작→점점 고조→완공 순간 절정), 보컬 없음")
    fact_notes: List[str] = Field(description="내레이션에 쓴 사실과 그 확실성 메모(내부 검수용)")


SYSTEM = """당신은 '뼈대부터 짓는다' 라는 한국어 쇼츠 시리즈의 기획자입니다.
시청자는 주제 하나가 선 스케치 → 뼈대 → 흰 점토 모형 → 실제 완성 모습으로 지어지는 30초 영상을 봅니다.
kind 판별: 사람이 들어가는 건축물·구조물(성, 탑, 다리, 등대 등)은 building, 그 밖의 물건(마이크, 헤드셋, 악기, 자동차, 비행기 등)은 object.
- building: 2단계(frame)는 '골조' — 기초·기둥·보·비계가 올라가는 공사 과정으로 설명. 4단계 이름은 '완공'.
- object: 2단계(frame)는 '골격' — 물체 모양을 따라 층층이 쌓이는 단면 링과 세로 갈빗대(내부 뼈대·프레임·부품 구조)로 설명. 공사·비계·기둥 같은 건축 용어는 쓰지 않음. 4단계 이름은 '완성'.

규칙
- 모든 화면 문구와 내레이션은 자연스러운 한국어. 내레이션은 말하듯이, 한 줄에 한 가지 정보.
- 사실은 널리 알려지고 확실한 것만 씁니다. 연도·수치가 불확실하면 쓰지 말고 구조 원리를 설명합니다.
- 실존 브랜드명·로고·상표는 쓰지 않습니다(제품이면 일반 명칭으로).
- image_prompt 규칙(영어): 대상 전체가 한 장에 들어오는 3/4 시점, 단색 밝은 회색 배경, 그림자 약하게, 사진처럼 사실적, 받침·사람·글자·로고·워터마크 없음, 대상만 단독으로. 건물이면 기단/석축까지 포함한 한 덩어리로, 주변 도시나 나무는 넣지 않음.
- stages는 key 순서 sketch, frame, model, real 로 4개.
- music_prompt는 주제의 문화·분위기에 맞는 악기를 고르고, 기존 곡·아티스트 이름은 쓰지 않습니다.
"""


def _client():
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY가 없습니다. 저장소 루트의 .env.example 을 .env 로 복사하고 본인 키를 넣으세요 (README '필수 준비물' 참고)")
    return anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


def make_plan(topic: str) -> dict:
    client = _client()
    try:
        resp = client.messages.parse(
            model=MODEL,
            max_tokens=16000,
            output_config={"effort": "high"},
            system=SYSTEM,
            messages=[{"role": "user", "content": f"주제: {topic}\n이 주제로 쇼츠 기획을 만들어 주세요."}],
            output_format=Plan,
        )
    except anthropic.AuthenticationError:
        raise RuntimeError("Claude API 키가 유효하지 않습니다")
    except anthropic.RateLimitError:
        raise RuntimeError("Claude API 요청 한도 초과, 잠시 뒤 다시 시도")
    except anthropic.APIStatusError as e:
        raise RuntimeError(f"Claude API 오류 {e.status_code}: {e.message}")
    except anthropic.APIConnectionError:
        raise RuntimeError("Claude API 연결 실패")
    if resp.stop_reason == "refusal":
        raise RuntimeError("Claude가 이 주제의 기획을 거절했습니다")
    plan = resp.parsed_output.model_dump()
    plan["topic"] = topic
    plan["model"] = MODEL
    plan["usage"] = {"input": resp.usage.input_tokens, "output": resp.usage.output_tokens}
    return plan


if __name__ == "__main__":
    import json, sys
    print(json.dumps(make_plan(sys.argv[1] if len(sys.argv) > 1 else "오사카성"), ensure_ascii=False, indent=1))
