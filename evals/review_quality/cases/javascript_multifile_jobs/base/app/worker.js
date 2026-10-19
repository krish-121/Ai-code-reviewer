/** Run one job, persist its outcome and propagate failures to the scheduler. */
async function perform(job, handler, repository) {
  try {
    const value = await handler(job.payload);
    repository.complete(job.id, value);
    return { id: job.id, value };
  } catch (error) {
    repository.fail(job.id, error);
    throw error;
  }
}
module.exports = { perform };
