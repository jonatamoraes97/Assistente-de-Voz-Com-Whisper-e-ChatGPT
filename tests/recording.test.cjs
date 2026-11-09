const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const notebook = JSON.parse(fs.readFileSync(path.join(__dirname,'../Assistente_de_Voz_com_Whisper_e_ChatGPT.ipynb'),'utf8'));
const helpers = notebook.cells.find(c => c.metadata.tags?.includes('helpers')).source.join('');
const source = helpers.match(/RECORD = r"""([\s\S]*?)"""/)[1];

function environment(options={}) {
  const tracks = [{stopped:false,stop() {this.stopped=true;}},{stopped:false,stop() {this.stopped=true;}}];
  const ctx = {
    setTimeout,clearTimeout,Blob,
    navigator:{mediaDevices:{async getUserMedia() {
      if (options.denied) throw Object.assign(new Error('denied'),{name:'NotAllowedError'});
      if (options.missing) throw Object.assign(new Error('missing'),{name:'NotFoundError'});
      return {getTracks:()=>tracks};
    }}},
    MediaRecorder: class {
      static isTypeSupported(type) {return !options.fallback && type.startsWith('audio/webm');}
      constructor(stream,config) {
        if (options.constructorError) throw new Error('constructor failed');
        this.state='inactive'; this.mimeType=options.fallback?'audio/ogg':config.mimeType;
      }
      start() {
        if (options.startError) throw new Error('start failed');
        this.state='recording';
        if (options.recorderError) setTimeout(()=>this.onerror(new Error('recorder failed')),0);
      }
      stop() {
        if (options.stopError) throw new Error('stop failed');
        this.state='inactive';
        if (!options.empty) this.ondataavailable({data:new Blob(['audio-bytes'],{type:this.mimeType})});
        this.onstop();
      }
    },
    FileReader: class {
      readAsDataURL(blob) {
        if (options.readerError) {this.onerror(); return;}
        if (options.readerAbort) {this.onabort(); return;}
        blob.arrayBuffer().then(data=>{
          this.result=`data:${blob.type};base64,${Buffer.from(data).toString('base64')}`;
          this.onload();
        });
      }
    },
  };
  vm.createContext(ctx); vm.runInContext(source,ctx);
  return {ctx,tracks};
}

test('captura preserva MIME, dados e libera todas as trilhas',{timeout:1000},async()=>{
  const {ctx,tracks}=environment();
  const result=await ctx.recordAudio(1);
  assert.equal(result.mimeType,'audio/webm;codecs=opus');
  assert.equal(Buffer.from(result.dataUrl.split(',')[1],'base64').toString(),'audio-bytes');
  assert.ok(tracks.every(t=>t.stopped));
});
test('fallback usa o MIME real escolhido pelo navegador',{timeout:1000},async()=>{
  const {ctx,tracks}=environment({fallback:true});
  assert.equal((await ctx.recordAudio(1)).mimeType,'audio/ogg');
  assert.ok(tracks.every(t=>t.stopped));
});
for (const [option,pattern] of [['denied',/Permissão/],['missing',/Nenhum microfone/],['constructorError',/constructor/],['startError',/start/],['stopError',/encerrar/],['recorderError',/gravação/],['empty',/vazia/],['readerError',/ler o áudio/],['readerAbort',/interrompida/]]) {
  test(`falha ${option} rejeita sem pendurar e libera recursos`,{timeout:1000},async()=>{
    const {ctx,tracks}=environment({[option]:true});
    await assert.rejects(ctx.recordAudio(1),pattern);
    if (!['denied','missing'].includes(option)) assert.ok(tracks.every(t=>t.stopped));
  });
}
test('rejeita duração inválida antes de pedir microfone',async()=>{
  for (const duration of [0,-1,NaN,Infinity,'5']) {
    const {ctx,tracks}=environment();
    await assert.rejects(ctx.recordAudio(duration),/duração/);
    assert.ok(tracks.every(t=>!t.stopped));
  }
});
test('navegador sem MediaRecorder informa incompatibilidade',async()=>{
  const {ctx}=environment();delete ctx.MediaRecorder;
  await assert.rejects(ctx.recordAudio(1),/navegador/);
});
