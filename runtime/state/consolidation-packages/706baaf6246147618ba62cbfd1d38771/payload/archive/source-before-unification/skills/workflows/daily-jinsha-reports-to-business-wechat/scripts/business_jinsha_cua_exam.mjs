import {runJinshaCuaExam} from '../../../.daily-jinsha-reports-core/scripts/jinsha_cua_exam.js';

const REFERENCE = Object.freeze({
  width: 1168,
  height: 686,
  paid: Object.freeze({x: 638 / 1168, y: 386 / 686}),
  net: Object.freeze({x: 808 / 1168, y: 386 / 686}),
});

function jpegDimensions(source) {
  const bytes = source instanceof Uint8Array ? source : Uint8Array.from(source || []);
  if(bytes.length < 4 || bytes[0] !== 0xff || bytes[1] !== 0xd8)throw Error('metric-screenshot-not-jpeg');
  let offset = 2;
  while(offset + 8 < bytes.length) {
    if(bytes[offset] !== 0xff) { offset += 1; continue; }
    const marker = bytes[offset + 1];
    if(marker === 0xd8 || marker === 0xd9) { offset += 2; continue; }
    const length = (bytes[offset + 2] << 8) | bytes[offset + 3];
    if(length < 2 || offset + 2 + length > bytes.length)break;
    if((marker >= 0xc0 && marker <= 0xc3) ||
       (marker >= 0xc5 && marker <= 0xc7) ||
       (marker >= 0xc9 && marker <= 0xcb) ||
       (marker >= 0xcd && marker <= 0xcf)) {
      return {
        height: (bytes[offset + 5] << 8) | bytes[offset + 6],
        width: (bytes[offset + 7] << 8) | bytes[offset + 8],
      };
    }
    offset += 2 + length;
  }
  throw Error('metric-screenshot-dimensions-missing');
}

function deriveMetricCoordinates(width, height) {
  if(!Number.isInteger(width) || !Number.isInteger(height) ||
     width < 900 || width > 2400 || height < 600 || height > 1600)
    throw Error(`metric-screenshot-geometry-unverified:${width}x${height}`);
  const aspect = width / height;
  if(aspect < 1.35 || aspect > 2.05)throw Error(`metric-screenshot-aspect-unverified:${aspect.toFixed(3)}`);
  const point = ratio => [Math.round(width * ratio.x), Math.round(height * ratio.y)];
  const paid = point(REFERENCE.paid);
  const net = point(REFERENCE.net);
  const safe = ([x,y]) => x > width * .45 && x < width * .75 && y > height * .42 && y < height * .66;
  if(!safe(paid) || !safe(net) || net[0] - paid[0] < width * .10)
    throw Error('metric-derived-target-outside-safe-region');
  return {paid, net, screenshot:{width,height}, method:'normalized-live-screenshot'};
}

async function runBusinessJinshaCuaExam(app, config) {
  if(config && Object.prototype.hasOwnProperty.call(config, 'metrics'))
    throw Error('raw-metric-coordinates-forbidden');
  const pageReady = state => state.includes('data.guoshuyufen.com/#/reportDownload') &&
    state.includes('单选按钮 美团外卖') && state.includes('单选按钮 淘宝闪购') &&
    /按钮 .*下载数据/.test(state);
  const before = await app.getAXState({emit:false, disableDiffing:true});
  if(!pageReady(before))throw Error('wrong-page');
  const screenshot = await app.getScreenshot({emit:false});
  const after = await app.getAXState({emit:false, disableDiffing:true});
  if(!pageReady(after))throw Error('page-changed-during-metric-preflight');
  const dimensions = jpegDimensions(screenshot);
  const metricLocator = deriveMetricCoordinates(dimensions.width, dimensions.height);
  const result = await runJinshaCuaExam(app, {
    ...config,
    metrics:{paid:metricLocator.paid, net:metricLocator.net},
  });
  return {...result, metricLocator};
}

export {REFERENCE, jpegDimensions, deriveMetricCoordinates, runBusinessJinshaCuaExam};
