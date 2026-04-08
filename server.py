"""
URANAI COSMOS - 無料全文開放版
5占術統合AI鑑定（広告収益モデル）

依存:
  pip install fastapi uvicorn anthropic python-multipart pydantic

環境変数:
  ANTHROPIC_API_KEY  ... Anthropic APIキー

起動:
  uvicorn server:app --host 0.0.0.0 --port 8000
"""

import os
from datetime import date
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import anthropic

# ── 設定 ──────────────────────────────────
ai = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

# ── プロンプト ─────────────────────────────
def get_today():
    return date.today().strftime("%Y年%m月%d日")

SYSTEM_PROMPT = """あなたは東洋・西洋の占術を統合したプロの鑑定師です。
HTMLタグは <h3> と <p> のみ使用。マークダウン不使用。絵文字不使用。

以下の形式で出力してください：

■ 1行目にスコアを出力：
SCORES:{{"総合":XX,"恋愛":XX,"仕事":XX,"金運":XX}}

■ 続けて以下の7セクションをすべて出力：

1. 総合鑑定（5占術の統合総評）
2. 手相から見るあなた
3. 星座と九星が示す運命
4. 数秘術・血液型が語る本質
5. 恋愛・対人運
6. 仕事・金運
7. 今後のアドバイス

各セクションは <h3>タイトル</h3> と <p>1〜2段落</p> で簡潔にまとめること。
1段落は3〜4文程度。冗長にならず核心を突いた鑑定を。
神秘的かつ温かみのある日本語で。必ず7セクションすべてを出力すること。"""


app = FastAPI(title="URANAI COSMOS")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/")
async def index():
    return FileResponse("index.html")


@app.get("/sitemap.xml")
async def sitemap():
    return FileResponse("sitemap.xml", media_type="application/xml")


@app.get("/robots.txt")
async def robots():
    return FileResponse("robots.txt", media_type="text/plain")


# ────────────────────────────────────────────
# 鑑定API（1回で全文生成）
# ────────────────────────────────────────────
class DivineRequest(BaseModel):
    name: str
    birth: str
    blood: str
    gender: str
    zodiac: str
    kyusei: str
    numerology: int
    image_b64: str
    image_type: str = "image/jpeg"


@app.post("/divine")
async def divine(req: DivineRequest):
    today = get_today()
    user_prompt = f"""【鑑定日】{today}
【鑑定対象】
名前：{req.name} / 生年月日：{req.birth} / 性別：{req.gender}
血液型：{req.blood}型 / 星座：{req.zodiac} / 九星気学：{req.kyusei}
数秘術ライフパスナンバー：{req.numerology}
添付の手のひら写真も合わせて、全セクションの鑑定を出力してください。"""

    try:
        response = ai.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": req.image_type, "data": req.image_b64}},
                {"type": "text", "text": user_prompt},
            ]}],
        )
        return JSONResponse({"result": response.content[0].text})
    except anthropic.APIError as e:
        print(f"[divine] Anthropic APIError: {e}")
        if getattr(e, "status_code", 0) == 400:
            detail = "ただいま鑑定サービスを準備中です。しばらく時間をおいてお試しください。"
        elif getattr(e, "status_code", 0) == 429:
            detail = "アクセスが集中しています。少し時間をおいて再度お試しください。"
        else:
            detail = "鑑定中にエラーが発生しました。しばらく時間をおいてお試しください。"
        raise HTTPException(503, detail)
    except Exception as e:
        print(f"[divine] Unexpected error: {e}")
        raise HTTPException(500, "予期しないエラーが発生しました。しばらく時間をおいてお試しください。")
