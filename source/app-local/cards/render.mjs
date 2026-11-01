import fs from 'node:fs';import path from 'node:path';import {fileURLToPath} from 'node:url';
import {bundle} from '@remotion/bundler';import {openBrowser,selectComposition,renderStill} from '@remotion/renderer';
const here=path.dirname(fileURLToPath(import.meta.url)),file=path.resolve(process.argv[2]),out=path.dirname(file),items=JSON.parse(fs.readFileSync(file,'utf8'));
const serveUrl=await bundle({entryPoint:path.join(here,'main.tsx'),publicDir:path.join(here,'../graphics/public'),outDir:path.join(out,'card-bundle')});
const browser=await openBrowser('chrome',{browserExecutable:process.env.MONTAJ_CHROME||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
try{for(const p of items){const composition=await selectComposition({serveUrl,id:'Card',inputProps:p,puppeteerInstance:browser});await renderStill({serveUrl,composition,inputProps:p,puppeteerInstance:browser,frame:0,imageFormat:'png',output:p.output});}}finally{await browser.close({silent:true})}
