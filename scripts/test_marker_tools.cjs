const {test} = require('node:test');
const assert = require('node:assert/strict');
const {edit} = require('../validation/marker-tools.js');

test('adding a cow two screen pixels from another preserves both markers', () => {
  const original = [[.5, .5]];
  assert.deepEqual(edit(original, [.502, .5], 'add', 1000, 1000), [[.5, .5], [.502, .5]]);
  assert.deepEqual(original, [[.5, .5]]);
});
test('removal selects the closest marker rather than the first nearby one', () => {
  const points = [[.5, .5], [.504, .5]];
  assert.deepEqual(edit(points, [.503, .5], 'remove', 1000, 1000), [[.5, .5]]);
});
test('removing empty space leaves markers intact', () => {
  const points = [[.5, .5]];
  assert.equal(edit(points, [.51, .5], 'remove', 1000, 1000), points);
});
