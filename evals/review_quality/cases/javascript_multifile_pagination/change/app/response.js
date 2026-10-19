/** Serialize a page and identify whether another complete window can follow. */
function response(result) {
  const consumed = (result.page + 1) * result.size;
  return { ...result, hasMore: consumed < result.total };
}
module.exports = { response };
