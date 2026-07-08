__version__ = "1.0.0"

import json
from ts_client import TSClient
from config_loader import load_merged_config


def _as_list(obj, preferred_keys=None):
    if preferred_keys is None:
        preferred_keys = []
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        for k in preferred_keys:
            v = obj.get(k)
            if isinstance(v, list):
                return v
        for v in obj.values():
            if isinstance(v, list):
                return v
    return []


def main():
    cfg = load_merged_config()

    client = TSClient(
        api_key=cfg["TS_API_KEY"],
        refresh_token=cfg["TS_REFRESH_TOKEN"],
        account_id=cfg["TS_ACCOUNT_ID"],
        live=cfg.get("LIVE_TRADING", False),
    )

    # Pull open/recent orders and positions. Endpoints may vary by account permissions.
    orders_resp = client._req(
        client.session.get,
        f"{client.base_url}/brokerage/accounts/{client.account_id}/orders"
    ) or {}

    positions_resp = client._req(
        client.session.get,
        f"{client.base_url}/brokerage/accounts/{client.account_id}/positions"
    ) or {}

    orders = _as_list(orders_resp, preferred_keys=["Orders", "orders"])
    positions = _as_list(positions_resp, preferred_keys=["Positions", "positions"])

    cancelled = []
    waiting_conversion = []
    butterflies = []

    # Cancel pending LONG orders that are NOT filled.
    pending_statuses = {
        "pending", "submitted", "working", "partiallyfilled", "received", "queued", "new"
    }

    long_actions = {
        "buy", "buytoopen", "buytocover", "long"
    }

    for o in orders:
        side = str(o.get("Side", o.get("TradeAction", ""))).strip().lower()
        status = str(o.get("Status", "")).strip().lower()

        is_long = side in long_actions
        not_filled_pending = status in pending_statuses

        if is_long and not_filled_pending:
            oid = o.get("OrderID") or o.get("orderId") or o.get("id")
            if oid:
                client.cancel_order(oid)
                cancelled.append({
                    "id": oid,
                    "symbol": o.get("Symbol", o.get("symbol", "")),
                    "status": o.get("Status", status)
                })

    # Leave conversions at brokerage (report only)
    for o in orders:
        text_blob = " ".join([
            str(o.get("Strategy", "")),
            str(o.get("Name", "")),
            str(o.get("Description", "")),
            str(o.get("Tag", "")),
        ]).lower()

        if "conversion" in text_blob:
            waiting_conversion.append({
                "id": o.get("OrderID") or o.get("orderId") or o.get("id"),
                "symbol": o.get("Symbol", o.get("symbol", "")),
                "status": o.get("Status", "")
            })

    # Report butterflies from position metadata
    for p in positions:
        text_blob = " ".join([
            str(p.get("Strategy", "")),
            str(p.get("Description", "")),
            str(p.get("AssetType", "")),
        ]).lower()

        if "butterfly" in text_blob:
            butterflies.append({
                "symbol": p.get("Symbol", p.get("symbol", "")),
                "qty": p.get("Quantity", p.get("quantity", 0))
            })

    print(json.dumps({
        "cancelled": cancelled,
        "waiting_conversion": waiting_conversion,
        "butterflies": butterflies
    }))


if __name__ == "__main__":
    main()