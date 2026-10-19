/** Public page numbers are zero-based; page size must be a positive integer. */
function validate(page, size) {
  if (!Number.isInteger(page) || page < 0) throw new Error('invalid page');
  if (!Number.isInteger(size) || size < 1 || size > 100) throw new Error('invalid size');
  return { page, size };
}
module.exports = { validate };
