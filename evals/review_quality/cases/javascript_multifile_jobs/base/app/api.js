/** Application entry point; callers use rejection to retry a failed batch. */
const { runBatch } = require('./scheduler');
const { report } = require('./report');

async function submit(jobs, handler, repository) {
  return report(await runBatch(jobs, handler, repository));
}
module.exports = { submit };
