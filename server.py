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

import os, uuid, time, json
from datetime import date
import stripe
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, FileResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import anthropic

# ── 設定 ──────────────────────────────────
BASE_URL   = os.environ.get("BASE_URL", "http://localhost:8000")
PRICE_YEN  = 300  # 円
STORE_FILE = "/tmp/uranai_sessions.json"

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

ai = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))


# ── セッション永続化ストア ─────────────────
def load_store() -> dict:
    """JSONファイルからセッションを読み込む"""
    try:
        if os.path.exists(STORE_FILE):
            with open(STORE_FILE, "r") as f:
                return json.load(f)
    except Exception as e:
        print(f"[store] load error: {e}")
    return {}

def save_store(store: dict):
    """セッションをJSONファイルに保存する"""
    try:
        with open(STORE_FILE, "w") as f:
            json.dump(store, f, ensure_ascii=False)
    except Exception as e:
        print(f"[store] save error: {e}")

def get_session(sid: str) -> dict | None:
    """セッションを取得"""
    store = load_store()
    return store.get(sid)

def set_session(sid: str, data: dict):
    """セッションを保存"""
    store = load_store()
    store[sid] = data
    # 古いセッションを自動削除（24時間以上）
    now = int(time.time())
    expired = [k for k, v in store.items() if now - v.get("created", 0) > 86400]
    for k in expired:
        del store[k]
    save_store(store)

def update_session(sid: str, updates: dict):
    """セッションを部分更新"""
    store = load_store()
    if sid in store:
        store[sid].update(updates)
        save_store(store)


# ── プロンプト ─────────────────────────────
def get_today():
    """今日の日付を返す"""
    return date.today().strftime("%Y年%m月%d日")

PREVIEW_SYSTEM = """あなたは東洋・西洋の占術を統合したプロの鑑定師です。
HTMLタグは <h3> と <p> のみ使用。マークダウン不使用。

以下の形式で出力してください：
1行目に必ずスコアを出力：
SCORES:{{"総合":XX,"恋愛":XX,"仕事":XX,"金運":XX}}

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
    today = get_today()
    user_prompt = f"""【鑑定日】{today}
【鑑定対象】
名前：{req.name} / 生年月日：{req.birth} / 性別：{req.gender}
血液型：{req.blood}型 / 星座：{req.zodiac} / 九星気学：{req.kyusei}
数秘術ライフパスナンバー：{req.numerology}
添付の手のひら写真も合わせて総合鑑定の冒頭を出力してください。"""

    try:
        response = ai.messages.create(
            model="claude-opus-4-6",
            max_tokens=1200,
            system=PREVIEW_SYSTEM,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": req.image_type, "data": req.image_b64}},
                {"type": "text", "text": user_prompt},
            ]}],
        )
        preview_html = response.content[0].text
        sid = str(uuid.uuid4())
        set_session(sid, {
            "status":       "PENDING",
            "payload":      req.dict(),
            "preview_html": preview_html,
            "created":      int(time.time()),
            "full_used":    False,
        })
        return JSONResponse({"session_id": sid, "preview": preview_html})
    except anthropic.APIError as e:
        print(f"[divine-preview] Anthropic APIError: {e}")
        if getattr(e, "status_code", 0) == 400:
            detail = "ただいま鑑定サービスを準備中です。しばらく時間をおいてお試しください。"
        elif getattr(e, "status_code", 0) == 429:
            detail = "アクセスが集中しています。少し時間をおいて再度お試しください。"
        else:
            detail = "鑑定中にエラーが発生しました。しばらく時間をおいてお試しください。"
        raise HTTPException(503, detail)
    except Exception as e:
        print(f"[divine-preview] Unexpected error: {e}")
        raise HTTPException(500, "予期しないエラーが発生しました。しばらく時間をおいてお試しください。")


# ────────────────────────────────────────────
# Step2: Stripe Checkout セッション作成
# ────────────────────────────────────────────
class PaymentRequest(BaseModel):
    session_id: str


@app.post("/create-checkout")
async def create_checkout(req: PaymentRequest):
    sid = req.session_id
    entry = get_session(sid)
    if not entry:
        raise HTTPException(404, "セッションが見つかりません。お手数ですが最初からやり直してください。")
    if int(time.time()) - entry["created"] > 3600:
        raise HTTPException(410, "セッションの有効期限が切れました。お手数ですが最初からやり直してください。")

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
        update_session(sid, {"stripe_checkout_id": checkout.id})
        return JSONResponse({"checkout_url": checkout.url})
    except stripe.error.StripeError as e:
        print(f"[create-checkout] StripeError: {e}")
        raise HTTPException(503, "決済システムに接続できませんでした。しばらく時間をおいてお試しください。")


# ────────────────────────────────────────────
# Step3: 支払い完了リダイレクト
# ────────────────────────────────────────────

# セッションのプレビュー結果を返す（決済後の画面復元用）
@app.get("/get-preview/{sid}")
async def get_preview(sid: str):
    entry = get_session(sid)
    if not entry:
        raise HTTPException(404, "セッションが見つかりません。")
    return JSONResponse({
        "preview": entry.get("preview_html", ""),
        "name":    entry.get("payload", {}).get("name", ""),
        "status":  entry.get("status", "PENDING"),
    })


@app.get("/payment-complete")
async def payment_complete(sid: str, stripe_session: str = ""):
    entry = get_session(sid)
    if not entry:
        # セッションが消えていてもStripeで支払い確認を試みる
        try:
            checkout = stripe.checkout.Session.retrieve(stripe_session)
            if checkout.payment_status == "paid":
                return RedirectResponse(f"/?unlocked=1&sid={sid}&verified=stripe")
        except Exception:
            pass
        return RedirectResponse("/?error=session_expired")

    try:
        checkout = stripe.checkout.Session.retrieve(stripe_session)
        if checkout.payment_status == "paid":
            update_session(sid, {"status": "COMPLETED"})
            return RedirectResponse(f"/?unlocked=1&sid={sid}")
        return RedirectResponse(f"/?error=payment_failed&sid={sid}")
    except Exception as e:
        print(f"[payment-complete] Error: {e}")
        return RedirectResponse("/?error=payment_error")


# ────────────────────────────────────────────
# Step4: 課金済み → 全文鑑定
# ────────────────────────────────────────────
class FullRequest(BaseModel):
    session_id: str


@app.post("/divine-full")
async def divine_full(req: FullRequest):
    entry = get_session(req.session_id)
    if not entry:
        raise HTTPException(404, "セッションが見つかりません。お手数ですが最初からやり直してください。")
    if entry["status"] != "COMPLETED":
        raise HTTPException(402, "お支払いが確認できませんでした。")
    if entry["full_used"]:
        raise HTTPException(409, "この鑑定の詳細結果は既に取得済みです。")

    d = entry["payload"]
    today = get_today()
    user_prompt = f"""【鑑定日】{today}
【鑑定対象】
名前：{d['name']} / 生年月日：{d['birth']} / 性別：{d['gender']}
血液型：{d['blood']}型 / 星座：{d['zodiac']} / 九星気学：{d['kyusei']}
数秘術ライフパスナンバー：{d['numerology']}
総合鑑定の続き（残り6セクション）を出力してください。"""

    try:
        response = ai.messages.create(
            model="claude-opus-4-6",
            max_tokens=4000,
            system=FULL_SYSTEM,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": d["image_type"], "data": d["image_b64"]}},
                {"type": "text", "text": user_prompt},
            ]}],
        )
        update_session(req.session_id, {"full_used": True})
        return JSONResponse({"full": response.content[0].text})
    except anthropic.APIError as e:
        print(f"[divine-full] Anthropic APIError: {e}")
        if getattr(e, "status_code", 0) == 400:
            detail = "ただいま鑑定サービスを準備中です。しばらく時間をおいてお試しください。"
        elif getattr(e, "status_code", 0) == 429:
            detail = "アクセスが集中しています。少し時間をおいて再度お試しください。"
        else:
            detail = "詳細鑑定の生成中にエラーが発生しました。しばらく時間をおいてお試しください。"
        raise HTTPException(503, detail)
    except Exception as e:
        print(f"[divine-full] Unexpected error: {e}")
        raise HTTPException(500, "予期しないエラーが発生しました。しばらく時間をおいてお試しください。")


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
        if sid:
            entry = get_session(sid)
            if entry:
                update_session(sid, {"status": "COMPLETED"})

    return JSONResponse({"status": "ok"})
