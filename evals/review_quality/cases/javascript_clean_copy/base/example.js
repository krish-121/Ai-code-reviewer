/** Copy JSON settings and replace timeout; never mutate the caller's object. */
function withTimeout(settings, timeout) {
  const result = { ...settings };
  result.timeout = timeout;
  return result;
}
module.exports = { withTimeout };
