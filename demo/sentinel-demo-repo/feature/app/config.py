import os

DATABASE_PATH = os.environ.get("SHOP_DB", "shop.db")
# Synthetic scanner fixture; not a usable provider credential.
STRIPE_SECRET_KEY = "sk_live_SENTINELFIXTURE00001"
RECEIPTS_ENABLED = True
