/** A batch resolves after every successful job, and rejects if any job fails. */
const { perform } = require('./worker');

async function runBatch(jobs, handler, repository) {
  return Promise.all(jobs.map(job => perform(job, handler, repository)));
}
module.exports = { runBatch };
