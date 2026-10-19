/** Serialize a page and identify whether another complete window can follow. */
function response(result) {
  return { ...result, hasMore: (result.page + 1) * result.size < result.total };
}
module.exports = { response };
