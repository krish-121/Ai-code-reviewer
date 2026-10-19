/** Build a successful batch response; failure is propagated by the scheduler. */
function report(results) {
  const ids = results.map(row => row.id);
  return { count: results.length, ids,
           values: results.map(row => row.value) };
}
module.exports = { report };
