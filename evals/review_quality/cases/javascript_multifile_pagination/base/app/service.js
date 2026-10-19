/** Convert a page number into the repository's row offset. */
const { validate } = require('./validation');
function list(catalog, page, size) {
  validate(page, size);
  return { items: catalog.window(page * size, size), total: catalog.count(), page, size };
}
module.exports = { list };
