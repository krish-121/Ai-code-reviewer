  /** Sort finite numbers ascending without modifying the input array. */
  function sortedNumbers(values) {
    const copy = values.slice();
return copy.sort((left, right) => left - right);
  }
  module.exports = { sortedNumbers };
