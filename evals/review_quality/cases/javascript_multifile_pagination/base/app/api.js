/** Supply defaults at the application boundary; zero is the first public page. */
const { list } = require('./service');
const { response } = require('./response');
function browse(catalog, query = {}) {
  return response(list(catalog, query.page ?? 0, query.size ?? 20));
}
module.exports = { browse };
