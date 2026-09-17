/* Private original-font extraction only; no browser, game, helper or model. */
'use strict';
const fs=require('fs'),path=require('path');
const [archive,modulePath,output]=process.argv.slice(2);
if(!archive||!modulePath||!output)throw Error('Usage: extract-gdi-atlas.cjs ARCHIVE EMULATORS_JS OUTPUT');
require(path.resolve(modulePath));
const emulators=global.emulators;emulators.pathPrefix=path.dirname(path.resolve(modulePath))+'/';
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const timeout=setTimeout(()=>{console.error('Bounded GDI extraction timed out');process.exit(1);},60000);
const config='[sdl]\nautolock=false\n[dosbox]\nmemsize=16\n[cpu]\ncore=auto\ncycles=auto\n[autoexec]\nmount c .\nc:\nwindows.bat\n';
(async()=>{let ci;try{
 ci=await emulators.dosboxNode([new Uint8Array(fs.readFileSync(archive)),{dosboxConf:config,jsdosConf:{version:'8.xx'}}]);
 let ready=false;
 for(let i=0;i<45;i++){
  await delay(1000);const tree=await ci.fsTree();
  if((tree.nodes||[]).some(node=>node.name==='ATDONE.TXT')){ready=true;break;}
 }
 if(!ready)throw Error('Original GDI probe did not finish');
 // A nonexistent fsReadFile leaves an occupied path promise in this js-dos
 // release. Inspect fsTree readiness first, then read each existing file once.
 fs.mkdirSync(output,{recursive:true});
 for(const name of ['ATLAS.BMP','GLYPHS.TSV','ATREG.BMP','REGULAR.TSV','ATDONE.TXT'])
  fs.writeFileSync(path.join(output,name.toLowerCase()),await ci.fsReadFile(name));
 }catch(error){console.error(String(error));process.exitCode=1;}
 finally{if(ci)await ci.exit();clearTimeout(timeout);}})();
