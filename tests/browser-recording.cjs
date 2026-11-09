// Executa a captura real do notebook no Chromium com um microfone simulado.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const http=require('node:http');
const {spawnSync}=require('node:child_process');
const notebook=JSON.parse(fs.readFileSync(path.join(__dirname,'../Assistente_de_Voz_com_Whisper_e_ChatGPT.ipynb'),'utf8'));
const source=notebook.cells.find(c=>c.metadata.tags?.includes('helpers')).source.join('').match(/RECORD = r"""([\s\S]*?)"""/)[1];

(async()=>{
  const server=http.createServer((req,res)=>{res.writeHead(200,{'Content-Type':'text/html'});res.end('<!doctype html><title>Teste local de gravação</title>');});
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  let browser;
  try {
    browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox','--use-fake-device-for-media-stream']});
    const context=await browser.newContext({permissions:['microphone']});
    const page=await context.newPage();
    const origin=`http://127.0.0.1:${server.address().port}`;
    await page.goto(origin);
    await page.addScriptTag({content:source});
    const result=await page.evaluate(async()=>{
      const original=navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
      let stream;
      navigator.mediaDevices.getUserMedia=async(...args)=>{stream=await original(...args);return stream;};
      const audio=await recordAudio(350);
      return {...audio,tracks:stream.getTracks().map(t=>t.readyState)};
    });
    assert.ok(result.tracks.length>0 && result.tracks.every(s=>s==='ended'));
    assert.match(result.mimeType,/audio\/webm/);
    const bytes=Buffer.from(result.dataUrl.split(',')[1],'base64');
    assert.ok(bytes.length>0);
    const ffprobe=spawnSync('ffprobe',['-v','error','-show_entries','stream=codec_name','-of','json','-i','pipe:0'],{input:bytes,encoding:'utf8'});
    assert.equal(ffprobe.status,0,ffprobe.stderr);
    const metadata=JSON.parse(ffprobe.stdout);
    assert.ok(metadata.streams.some(s=>s.codec_name==='opus'));
    const cdp=await context.newCDPSession(page);
    const {targetInfo}=await cdp.send('Target.getTargetInfo');
    await cdp.send('Browser.setPermission',{permission:{name:'microphone'},setting:'denied',origin,browserContextId:targetInfo.browserContextId});
    assert.equal(await page.evaluate(async()=>(await navigator.permissions.query({name:'microphone'})).state),'denied');
    const denied=await page.evaluate(async()=>{
      try {await recordAudio(20);return 'unexpected success';} catch(error) {return error.message;}
    });
    assert.match(denied,/Permissão do microfone negada/);
    console.log(JSON.stringify({browser:await browser.version(),capture:'ok',permission_denied:'ok',tracks_released:'ok',mime:result.mimeType,codec:'opus',audio_bytes:bytes.length,device:'simulado; sem microfone físico'}));
    await context.close();
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve=>server.close(resolve));
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
