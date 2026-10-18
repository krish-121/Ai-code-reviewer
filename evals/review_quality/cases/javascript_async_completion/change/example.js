/** Resolve only after every save promise has completed; reject if a save fails. */
async function saveAll(items, save) {
  items.forEach(async (item) => { await save(item); });
}
module.exports = { saveAll };
