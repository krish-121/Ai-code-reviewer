/** Supply defaults at the application boundary; zero is the first public page. */
const { list } = require('./service');
const { response } = require('./response');
function browse(catalog, query = {}) {
  const page = query.page ?? 0;
  const size = query.size ?? 20;
  return response(list(catalog, page, size));
}
module.exports = { browse };
