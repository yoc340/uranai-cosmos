"""
URANAI COSMOS - Stripe決済統合版
フリーミアム型（無料プレビュー → Stripe課金 → 全文解放）

依存:
  pip install fastapi uvicorn anthropic stripe python-multipart pydantic

環境変数:
  ANTHROPIC_API_KEY       ... Anthropic APIキー
  STRIPE_SECRET_KEY       ... Stripe シークレットキー（sk_live_xxx or sk_test_xxx）
  STRIPE_WEBHOOK_SECRET   ... Stripe Webhook署名シークレット（whsec_xxx）
  BASE_URL                ... 公開URL例: https://uranai-cosmos.onrender.com

起動:
  uvicorn server:app --host 0.0.0.0 --port 8000
"""

import os, uuid, time
import stripe
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, FileResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import anthropic

# ── 設定 ──────────────────────────────────
BASE_URL   = os.environ.get("BASE_URL", "http://localhost:8000")
PRICE_YEN  = 300  # 円

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

ai = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

# ── プロンプト ─────────────────────────────
PREVIEW_SYSTEM = """あなたは東洋・西洋の占術を統合したプロの鑑定師です。
HTMLタグは <h3> と <p> のみ使用。マークダウン不使用。

以下の形式で出力してください：
1行目に必ずスコアを出力：
SCORES:{"総合":XX,"恋愛":XX,"仕事":XX,"金運":XX}

次に「総合鑑定」セクションのみ出力（<h3>総合鑑定</h3> + <p>2〜3段落）。
5つの占術を統合した総評。神秘的かつ温かみのある日本語で。
最後の段落は続きが気になる引きのある文章で終わらせること。"""

FULL_SYSTEM = """あなたは東洋・西洋の占術を統合したプロの鑑定師です。
HTMLタグは <h3> と <p> のみ使用。マークダウン不使用。

以下の6セクションを詳細に出力（総合鑑定は省略）：
1. 手相から見るあなた
2. 星座と九星が示す運命
3. 数秘術・血液型が語る本質
4. 恋愛・対人運
5. 仕事・金運
6. 今後のアドバイス

各セクションは <h3> タイトルと <p> 2〜3段落で。神秘的かつ温かみのある日本語で。"""

# ── セッションストア ───────────────────────
# { session_id: { status, payload, preview_html, created, full_used } }
store: dict = {}

app = FastAPI(title="URANAI COSMOS")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/")
async def index():
    return FileResponse("index.html")


# ────────────────────────────────────────────
# Step1: 無料プレビュー鑑定
# ────────────────────────────────────────────
class PreviewRequest(BaseModel):
    name: str
    birth: str
    blood: str
    gender: str
    zodiac: str
    kyusei: str
    numerology: int
    image_b64: str
    image_type: str = "image/jpeg"


@app.post("/divine-preview")
async def divine_preview(req: PreviewRequest):
    user_prompt = f"""【鑑定対象】
名前：{req.name} / 生年月日：{req.birth} / 性別：{req.gender}
血液型：{req.blood}型 / 星座：{req.zodiac} / 九星気学：{req.kyusei}
数秘術ライフパスナンバー：{req.numerology}
添付の手のひら写真も合わせて総合鑑定の冒頭を出力してください。"""

    try:
        response = ai.messages.create(
            model="claude-opus-4-5",
            max_tokens=800,
            system=PREVIEW_SYSTEM,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": req.image_type, "data": req.image_b64}},
                {"type": "text", "text": user_prompt},
            ]}],
        )
        preview_html = response.content[0].text
        sid = str(uuid.uuid4())
        store[sid] = {
            "status":       "PENDING",
            "payload":      req.dict(),
            "preview_html": preview_html,
            "created":      int(time.time()),
            "full_used":    False,
        }
        return JSONResponse({"session_id": sid, "preview": preview_html})
    except anthropic.APIError as e:
        raise HTTPException(502, str(e))


# ────────────────────────────────────────────
# Step2: Stripe Checkout セッション作成
# ────────────────────────────────────────────
class PaymentRequest(BaseModel):
    session_id: str


@app.post("/create-checkout")
async def create_checkout(req: PaymentRequest):
    sid = req.session_id
    if sid not in store:
        raise HTTPException(404, "session not found")
    if int(time.time()) - store[sid]["created"] > 3600:
        raise HTTPException(410, "session expired")

    try:
        checkout = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency":     "jpy",
                    "unit_amount":  PRICE_YEN,
                    "product_data": {
                        "name":        "URANAI COSMOS 詳細鑑定",
                        "description": "手相・星座・九星気学・数秘術・血液型の5占術による総合鑑定（全文）",
                    },
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=f"{BASE_URL}/payment-complete?sid={sid}&stripe_session={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{BASE_URL}/?cancelled=1&sid={sid}",
            metadata={"uranai_session_id": sid},
        )
        store[sid]["stripe_checkout_id"] = checkout.id
        return JSONResponse({"checkout_url": checkout.url})
    except stripe.error.StripeError as e:
        raise HTTPException(502, str(e))


# ────────────────────────────────────────────
# Step3: 支払い完了リダイレクト
# ────────────────────────────────────────────
@app.get("/payment-complete")
async def payment_complete(sid: str, stripe_session: str = ""):
    if sid not in store:
        return RedirectResponse("/?error=invalid_session")
    try:
        checkout = stripe.checkout.Session.retrieve(stripe_session)
        if checkout.payment_status == "paid":
            store[sid]["status"] = "COMPLETED"
            return RedirectResponse(f"/?unlocked=1&sid={sid}")
        return RedirectResponse(f"/?error=payment_failed&sid={sid}")
    except Exception as e:
        return RedirectResponse(f"/?error={e}")


# ────────────────────────────────────────────
# Step4: 課金済み → 全文鑑定
# ────────────────────────────────────────────
class FullRequest(BaseModel):
    session_id: str


@app.post("/divine-full")
async def divine_full(req: FullRequest):
    entry = store.get(req.session_id)
    if not entry:
        raise HTTPException(404, "session not found")
    if entry["status"] != "COMPLETED":
        raise HTTPException(402, "payment required")
    if entry["full_used"]:
        raise HTTPException(409, "already used")

    d = entry["payload"]
    user_prompt = f"""【鑑定対象】
名前：{d['name']} / 生年月日：{d['birth']} / 性別：{d['gender']}
血液型：{d['blood']}型 / 星座：{d['zodiac']} / 九星気学：{d['kyusei']}
数秘術ライフパスナンバー：{d['numerology']}
総合鑑定の続き（残り6セクション）を出力してください。"""

    try:
        response = ai.messages.create(
            model="claude-opus-4-5",
            max_tokens=2048,
            system=FULL_SYSTEM,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": d["image_type"], "data": d["image_b64"]}},
                {"type": "text", "text": user_prompt},
            ]}],
        )
        entry["full_used"] = True
        return JSONResponse({"full": response.content[0].text})
    except anthropic.APIError as e:
        raise HTTPException(502, str(e))


# ────────────────────────────────────────────
# Stripe Webhook（本番推奨）
# ────────────────────────────────────────────
@app.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig, WEBHOOK_SECRET)
    except Exception:
        raise HTTPException(400, "invalid signature")

    if event["type"] == "checkout.session.completed":
        cs = event["data"]["object"]
        sid = cs.get("metadata", {}).get("uranai_session_id")
        if sid and sid in store:
            store[sid]["status"] = "COMPLETED"

    return JSONResponse({"status": "ok"})
