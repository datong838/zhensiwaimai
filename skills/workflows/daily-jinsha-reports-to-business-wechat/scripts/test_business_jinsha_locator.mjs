import assert from 'node:assert/strict';
import {
  deriveMetricCoordinates,
  jpegDimensions,
} from './business_jinsha_cua_exam.mjs';

function fakeJpeg(width, height) {
  return Uint8Array.from([
    0xff,0xd8,
    0xff,0xc0,0x00,0x0b,0x08,
    (height >> 8) & 0xff,height & 0xff,
    (width >> 8) & 0xff,width & 0xff,
    0x03,0x01,0x11,0x00,
    0xff,0xd9,
  ]);
}

assert.deepEqual(jpegDimensions(fakeJpeg(1168,686)), {width:1168,height:686});
assert.deepEqual(deriveMetricCoordinates(1168,686).paid, [638,386]);
assert.deepEqual(deriveMetricCoordinates(1168,686).net, [808,386]);
assert.notDeepEqual(deriveMetricCoordinates(1232,738).paid, [638,386]);
assert.throws(() => deriveMetricCoordinates(600,1200), /geometry-unverified/);
assert.throws(() => jpegDimensions(Uint8Array.from([1,2,3])), /not-jpeg/);
console.log('business Jinsha dynamic metric locator checks passed');
