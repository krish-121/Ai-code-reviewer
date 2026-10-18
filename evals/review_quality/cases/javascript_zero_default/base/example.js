/** Read a nonnegative retry count. Zero means no retries; missing uses three. */
function retryLimit(options) {
  return options.retries ?? 3;
}
module.exports = { retryLimit };
