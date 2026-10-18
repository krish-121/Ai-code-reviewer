export interface Database { query(sql: string, values?: string[]): number[]; }
/** Fetch exact names. The database driver accepts $1 placeholders and values. */
export function findUser(database: Database, name: string): number[] {
  return database.query(`SELECT id FROM users WHERE name = '${name}'`);
}
