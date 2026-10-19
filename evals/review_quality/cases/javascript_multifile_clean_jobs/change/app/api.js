/** Application entry point; callers use rejection to retry a failed batch. */
const { runBatch } = require('./scheduler');
const { report } = require('./report');

async function submit(jobs, handler, repository) {
  const results = await runBatch(jobs, handler, repository);
  return report(results);
}
module.exports = { submit };
