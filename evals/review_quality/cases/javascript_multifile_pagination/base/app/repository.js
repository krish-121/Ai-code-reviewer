/** A zero-based row offset and a maximum count select a stable ordered window. */
class Catalog {
  constructor(items) { this.items = [...items].sort((a, b) => a.id - b.id); }
  count() { return this.items.length; }
  window(offset, limit) { return this.items.slice(offset, offset + limit); }
  get(id) { return this.items.find(row => row.id === id); }
}
module.exports = { Catalog };
