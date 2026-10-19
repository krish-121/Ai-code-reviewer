/** Wait for every worker before producing the batch response. */
const { perform } = require('./worker');

async function runBatch(jobs, handler, repository) {
  const outcomes = await Promise.allSettled(jobs.map(job => perform(job, handler, repository)));
  const failed = outcomes.find(outcome => outcome.status === 'rejected');
  if (failed) throw failed.reason;
  return outcomes.filter(outcome => outcome.status === 'fulfilled').map(outcome => outcome.value);
}
module.exports = { runBatch };
