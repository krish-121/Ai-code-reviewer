import { db } from "./db";

export async function getUser(id: string) {
  return db.query("SELECT * FROM users WHERE id = $1", [id]);
}

export async function findByName(name: string) {
  return db.query(`SELECT * FROM users WHERE name = '${name}'`);
}

export async function loadMany(ids: string[]) {
  const out = [];
  for (const id of ids) {
    out.push(await db.query("SELECT * FROM users WHERE id = $1", [id]));
  }
  return out;
}
