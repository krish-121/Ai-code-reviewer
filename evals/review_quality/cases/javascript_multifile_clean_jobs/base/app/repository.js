/** Record individual outcomes; a batch failure must remain observable to callers. */
class JobRepository {
  constructor() { this.outcomes = new Map(); }
  complete(id, value) { this.outcomes.set(id, { state: 'complete', value }); }
  fail(id, error) { this.outcomes.set(id, { state: 'failed', message: error.message }); }
  get(id) { return this.outcomes.get(id); }
  completedCount() {
    return [...this.outcomes.values()].filter(row => row.state === 'complete').length;
  }
}
module.exports = { JobRepository };
