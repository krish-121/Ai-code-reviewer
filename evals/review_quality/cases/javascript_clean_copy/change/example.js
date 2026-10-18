/** Copy JSON settings and replace timeout; never mutate the caller's object. */
function withTimeout(settings, timeout) {
  return { ...settings, timeout };
}
module.exports = { withTimeout };
