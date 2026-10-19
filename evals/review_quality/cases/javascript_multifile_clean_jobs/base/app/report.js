/** Build a successful batch response; failure is propagated by the scheduler. */
function report(results) {
  return { count: results.length, ids: results.map(row => row.id),
           values: results.map(row => row.value) };
}
module.exports = { report };
