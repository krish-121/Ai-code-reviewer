/** Immutable job values passed between the queue, worker and reporting layer. */
function job(id, payload) {
  if (!id) throw new Error('missing job id');
  return { id, payload };
}
module.exports = { job };
