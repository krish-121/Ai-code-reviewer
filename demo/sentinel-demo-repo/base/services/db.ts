import { Pool } from "pg";

export const db = {
  pool: new Pool({ connectionString: process.env.DATABASE_URL }),
  async query(sql: string, params: unknown[] = []): Promise<any[]> {
    const result = await this.pool.query(sql, params);
    return result.rows;
  },
};
