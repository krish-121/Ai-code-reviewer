/** Fetch exact names. The database driver accepts $1 placeholders and values. */
function findUser(database, name) {
  return database.query(`SELECT id FROM users WHERE name = '${name}'`);
}
module.exports = { findUser };
