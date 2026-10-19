/** Store stable integer IDs and labels without exposing caller-owned objects. */
function item(id, label) {
  if (!Number.isInteger(id) || id < 1 || !label) throw new Error('invalid item');
  return Object.freeze({ id, label });
}
module.exports = { item };
