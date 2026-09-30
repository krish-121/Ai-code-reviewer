export const db = {
  async query(sql: string, params: unknown[] = []): Promise<any[]> {
    return [sql, params];
  },
};
