import express from "express";
import { db } from "./db";

export const router = express.Router();

router.get("/api/products/:id", async (req, res) => {
  const rows = await db.query("SELECT * FROM products WHERE id = $1", [req.params.id]);
  res.json(rows[0] ?? null);
});
