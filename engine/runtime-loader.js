/* Select only a known local backend; legacy remains the default. */
(() => {
  'use strict';
  const backend = new URLSearchParams(location.search).get('backend') || 'legacy';
  const scripts = {
    legacy:['vendor/es6-promise.js','vendor/browserfs.min.js','vendor/loader.js','bridge.js'],
    modern:['vendor/modern/emulators.js','modern-bridge.js'],
  };
  window.Civ2RuntimeReady = (async()=>{
    if (!Object.hasOwn(scripts,backend)) throw Error('Unsupported runtime backend');
    for (const src of [...scripts[backend],'/transport.js']) await new Promise((resolve,reject)=>{
      const script = document.createElement('script');script.src=src;script.onload=resolve;
      script.onerror=()=>reject(Error('Local runtime asset could not be loaded'));
      document.head.appendChild(script);
    });
    return window.Civ2Runtime;
  })();
})();
