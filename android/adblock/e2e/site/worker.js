fetch('/ads/tark-test-ad.js?worker').then(() => postMessage('loaded'), () => postMessage('failed'));
