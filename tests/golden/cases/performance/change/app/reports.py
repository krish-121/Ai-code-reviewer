def total(rows):
    return sum(r["amount"] for r in rows)


def load_orders(conn, customer_ids):
    out = []
    for cid in customer_ids:
        out.extend(conn.execute("SELECT * FROM orders WHERE customer_id = ?", (cid,)).fetchall())
    return out


def common_skus(left, right):
    shared = []
    for a in left:
        for b in right:
            if a["sku"] == b["sku"]:
                shared.append(a)
    return shared


async def refresh(client, urls):
    import time

    for url in urls:
        time.sleep(0.5)
        await client.get(url)
