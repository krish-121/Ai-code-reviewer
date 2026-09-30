import express from "express";
import { db } from "./db";

export const router = express.Router();

router.get("/api/products/:id", async (req, res) => {
  const rows = await db.query("SELECT * FROM products WHERE id = $1", [req.params.id]);
  res.json(rows[0] ?? null);
});

router.get("/api/products", async (req, res) => {
  const term = String(req.query.q ?? "");
  const rows = await db.query(`SELECT * FROM products WHERE name ILIKE '%${term}%'`);
  res.json(rows);
});

export async function pricesFor(ids: number[]): Promise<Record<number, number>> {
  const prices: Record<number, number> = {};
  for (const id of ids) {
    const rows = await db.query("SELECT price FROM products WHERE id = $1", [id]);
    prices[id] = rows[0]?.price ?? 0;
  }
  return prices;
}
