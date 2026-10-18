/** Sort finite numbers ascending without modifying the input array. */
function sortedNumbers(values) {
  return [...values].sort((left, right) => left - right);
}
module.exports = { sortedNumbers };
