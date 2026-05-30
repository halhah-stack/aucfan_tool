"""
sp_api_client.py — Amazon SP-API クライアント

【対応API】
  - LWA アクセストークン取得
  - Catalog Items API v2022-04-01  : 商品情報（タイトル・ランキング・カテゴリ）
  - Products Fees API v0           : FBA手数料見積もり

【使い方】
  from sp_api_client import SpApiClient
  client = SpApiClient()
  info = client.fetch_product_info("B0XXXXXXXX", price=3000)
  # info = {
  #   "asin": "B0XXXXXXXX",
  #   "title": "...",
  #   "brand": "...",
  #   "rank": 1234,
  #   "category": "ホーム&キッチン",
  #   "price": 3000,          # 参照価格（渡した値）
  #   "fba_fee": 450,         # FBA手数料（円）
  #   "referral_fee": 240,    # 販売手数料（円）
  #   "total_fee": 690,       # 合計手数料（円）
  #   "error": None,          # エラーメッセージ（失敗時）
  # }
"""
import time
import logging
import requests
import config

logger = logging.getLogger(__name__)

# SP-API エンドポイント（日本）
_SP_API_BASE = "https://sellingpartnerapi-fe.amazon.com"
_LWA_TOKEN_URL = "https://api.amazon.com/auth/o2/token"


class SpApiClient:
    """Amazon SP-API クライアント（日本マーケットプレイス向け）"""

    def __init__(self):
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0

    # ─────────────────────────────────────────────
    # アクセストークン管理
    # ─────────────────────────────────────────────

    def _get_access_token(self) -> str:
        """
        LWA (Login with Amazon) からアクセストークンを取得する。
        有効期限内であればキャッシュを返す（有効期間は3600秒）。
        """
        now = time.time()
        if self._access_token and now < self._token_expires_at - 60:
            return self._access_token

        if not config.SP_API_REFRESH_TOKEN:
            raise RuntimeError("SP_API_REFRESH_TOKEN が設定されていません。.env を確認してください。")
        if not config.SP_API_CLIENT_ID or not config.SP_API_CLIENT_SECRET:
            raise RuntimeError("SP_API_CLIENT_ID / SP_API_CLIENT_SECRET が設定されていません。")

        resp = requests.post(_LWA_TOKEN_URL, data={
            "grant_type":    "refresh_token",
            "refresh_token": config.SP_API_REFRESH_TOKEN,
            "client_id":     config.SP_API_CLIENT_ID,
            "client_secret": config.SP_API_CLIENT_SECRET,
        }, timeout=15)

        if resp.status_code != 200:
            raise RuntimeError(f"LWAトークン取得失敗: {resp.status_code} {resp.text}")

        data = resp.json()
        self._access_token = data["access_token"]
        self._token_expires_at = now + data.get("expires_in", 3600)
        logger.debug("[SP-API] アクセストークン取得成功")
        return self._access_token

    def _headers(self) -> dict:
        return {
            "x-amz-access-token": self._get_access_token(),
            "Content-Type": "application/json",
        }

    # ─────────────────────────────────────────────
    # Catalog Items API
    # ─────────────────────────────────────────────

    def get_catalog_item(self, asin: str) -> dict:
        """
        Catalog Items API v2022-04-01 で商品情報を取得する。

        Returns:
            {
              "title": str,
              "brand": str,
              "rank": int | None,
              "category": str,
              "list_price": int | None,   # 参考価格（円）
            }
        """
        url = f"{_SP_API_BASE}/catalog/2022-04-01/items/{asin}"
        params = {
            "marketplaceIds": config.SP_API_MARKETPLACE_ID,
            "includedData": "attributes,salesRanks,summaries",
        }
        resp = requests.get(url, headers=self._headers(), params=params, timeout=15)

        if resp.status_code == 404:
            raise ValueError(f"ASIN {asin} が見つかりません（404）")
        if resp.status_code != 200:
            raise RuntimeError(f"Catalog Items API エラー: {resp.status_code} {resp.text}")

        data = resp.json()

        # タイトル・ブランド
        title = ""
        brand = ""
        summaries = data.get("summaries", [])
        for s in summaries:
            if s.get("marketplaceId") == config.SP_API_MARKETPLACE_ID:
                title = s.get("itemName", "")
                brand = s.get("brand", "")
                break

        # 参考価格
        list_price = None
        attrs = data.get("attributes", {})
        list_price_attr = attrs.get("list_price", [])
        if list_price_attr:
            lp = list_price_attr[0]
            if lp.get("currency", "JPY") == "JPY":
                list_price = int(lp.get("value", 0))

        # ランキング・カテゴリ
        rank = None
        category = ""
        sales_ranks = data.get("salesRanks", [])
        for sr in sales_ranks:
            if sr.get("marketplaceId") == config.SP_API_MARKETPLACE_ID:
                ranks = sr.get("ranks", [])
                if ranks:
                    # 最初のランキング（通常はメインカテゴリ）を使用
                    rank = ranks[0].get("rank")
                    category = ranks[0].get("title", "")
                break

        return {
            "title":      title,
            "brand":      brand,
            "rank":       rank,
            "category":   category,
            "list_price": list_price,
        }

    # ─────────────────────────────────────────────
    # Product Pricing API（現在の出品価格取得）
    # ─────────────────────────────────────────────

    def get_listing_price(self, asin: str) -> int | None:
        """
        Product Pricing API v0 で現在の最安値出品価格を取得する。
        参考価格（list_price）が取れない場合のフォールバックとして使用。

        Returns:
            int | None — 最安値（円）。取得できなければ None。
        """
        url = f"{_SP_API_BASE}/products/pricing/v0/price"
        params = {
            "MarketplaceId": config.SP_API_MARKETPLACE_ID,
            "ItemType":      "Asin",
            "Asins":         asin,
        }
        try:
            resp = requests.get(url, headers=self._headers(), params=params, timeout=15)
            if resp.status_code != 200:
                logger.warning(f"[SP-API] Pricing API {resp.status_code}: {resp.text[:200]}")
                return None
            data = resp.json()
            # payload は list[{ASIN, status, Product}]
            for item in data.get("payload", []):
                if item.get("status") != "Success":
                    continue
                offers = (
                    item.get("Product", {})
                        .get("Offers", [])
                )
                for offer in offers:
                    lp = offer.get("BuyingPrice", {}).get("ListingPrice", {})
                    if lp.get("CurrencyCode") == "JPY":
                        return int(float(lp.get("Amount", 0)))
        except Exception as e:
            logger.warning(f"[SP-API] Pricing API エラー: {e}")
        return None

    # ─────────────────────────────────────────────
    # Products Fees API
    # ─────────────────────────────────────────────

    def get_fees_estimate(self, asin: str, price: int) -> dict:
        """
        Products Fees API v0 で FBA 手数料見積もりを取得する。

        Args:
            asin:  対象ASIN
            price: 想定販売価格（円）

        Returns:
            {
              "fba_fee":      int,   # FBA配送代行手数料（円）
              "referral_fee": int,   # 販売手数料（円）
              "total_fee":    int,   # 合計（円）
            }
        """
        url = f"{_SP_API_BASE}/products/fees/v0/items/{asin}/feesEstimate"
        body = {
            "FeesEstimateRequest": {
                "MarketplaceId":     config.SP_API_MARKETPLACE_ID,
                "IsAmazonFulfilled": True,
                "PriceToEstimateFees": {
                    "ListingPrice": {
                        "CurrencyCode": "JPY",
                        "Amount":       float(price),
                    },
                    "Shipping": {
                        "CurrencyCode": "JPY",
                        "Amount":       0.0,
                    },
                },
                "Identifier": f"req_{asin}_{price}",
            }
        }
        logger.debug(f"[SP-API] Fees request body: {body}")
        resp = requests.post(url, headers=self._headers(), json=body, timeout=15)

        if resp.status_code != 200:
            raise RuntimeError(f"Products Fees API エラー: {resp.status_code} {resp.text}")

        data = resp.json()
        # ClientError チェック
        result_obj = data.get("payload", {}).get("FeesEstimateResult", {})
        if result_obj.get("Status") == "ClientError":
            err = result_obj.get("Error", {})
            raise RuntimeError(
                f"Products Fees API ClientError: [{err.get('Code')}] {err.get('Message')}"
            )

        # レスポンス構造: payload.FeesEstimateResult.FeesEstimate.FeeDetailList
        try:
            fee_detail = result_obj["FeesEstimate"]["FeeDetailList"]
        except (KeyError, TypeError):
            raise RuntimeError(f"Products Fees API: 予期しないレスポンス構造 {data}")

        fba_fee = 0
        referral_fee = 0
        for item in fee_detail:
            name = item.get("FeeType", "")
            amount = int(item.get("FeeAmount", {}).get("Amount", 0))
            if "FBAFees" in name or "FulfillmentFee" in name:
                fba_fee += amount
            elif "ReferralFee" in name or "Commission" in name:
                referral_fee += amount

        return {
            "fba_fee":      fba_fee,
            "referral_fee": referral_fee,
            "total_fee":    fba_fee + referral_fee,
        }

    # ─────────────────────────────────────────────
    # 統合取得
    # ─────────────────────────────────────────────

    def fetch_product_info(self, asin: str, price: int | None = None) -> dict:
        """
        Catalog Items API + Products Fees API を呼んで商品情報を一括返却する。

        Args:
            asin:  対象ASIN
            price: 想定販売価格（円）。None の場合は参考価格を使用。

        Returns:
            {
              "asin": str,
              "title": str,
              "brand": str,
              "rank": int | None,
              "category": str,
              "list_price": int | None,
              "price": int | None,       # 手数料計算に使った価格
              "fba_fee": int | None,
              "referral_fee": int | None,
              "total_fee": int | None,
              "error": str | None,       # エラー時のみ
            }
        """
        result = {
            "asin":         asin,
            "title":        "",
            "brand":        "",
            "rank":         None,
            "category":     "",
            "list_price":   None,
            "price":        price,
            "fba_fee":      None,
            "referral_fee": None,
            "total_fee":    None,
            "error":        None,
        }

        try:
            catalog = self.get_catalog_item(asin)
            result.update(catalog)

            # 価格の優先順位: ① ユーザー入力 → ② Catalog list_price → ③ Pricing API 最安値
            effective_price = price or catalog.get("list_price")
            if not effective_price:
                effective_price = self.get_listing_price(asin)
                if effective_price:
                    logger.info(f"[SP-API] {asin}: Pricing API から価格取得 ¥{effective_price}")
            result["price"] = effective_price

            if effective_price and effective_price > 0:
                try:
                    fees = self.get_fees_estimate(asin, effective_price)
                    result.update(fees)
                except RuntimeError as fee_err:
                    # FBA手数料取得失敗 → 自己発送専用ASINの可能性
                    logger.warning(f"[SP-API] {asin}: FBA手数料取得失敗（自己発送専用ASINの可能性）: {fee_err}")
                    result["fee_error"] = str(fee_err)
            else:
                logger.warning(f"[SP-API] {asin}: 価格を取得できなかったため手数料計算をスキップ")

        except Exception as e:
            logger.error(f"[SP-API] fetch_product_info エラー ({asin}): {e}")
            result["error"] = str(e)

        return result


# ─────────────────────────────────────────────
# シングルトンインスタンス（アプリ全体で共有）
# ─────────────────────────────────────────────
_client: SpApiClient | None = None


def get_client() -> SpApiClient:
    """SP-API クライアントのシングルトンを返す"""
    global _client
    if _client is None:
        _client = SpApiClient()
    return _client
