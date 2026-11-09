"""Regressão offline das células reais do notebook; nenhuma chamada externa é permitida."""
import base64
import contextlib
import io
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import httpx
import nbformat
import openai

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = nbformat.read(ROOT / 'Assistente_de_Voz_com_Whisper_e_ChatGPT.ipynb', as_version=4)
CELLS = {c.metadata['tags'][0]: c.source for c in NOTEBOOK.cells if c.cell_type == 'code'}
DUMMY = 'dummy-offline-not-a-secret'


def execute(tag, scope):
    with contextlib.redirect_stdout(io.StringIO()):
        exec(compile(CELLS[tag], f'<notebook:{tag}>', 'exec'), scope)


def captured(mime='audio/webm', content=b'\x1a\x45\xdf\xa3fake-webm'):
    return {'mimeType': mime, 'dataUrl': f'data:{mime};base64,' + base64.b64encode(content).decode()}


def completion(content='Resposta em português.', finish_reason='stop'):
    return {
        'id': 'chatcmpl-offline', 'object': 'chat.completion', 'created': 0, 'model': 'gpt-4',
        'choices': [{'index': 0, 'finish_reason': finish_reason, 'message': {'role': 'assistant', 'content': content}}],
    }


class NotebookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        old_cwd = Path.cwd()
        os.chdir(self.tmp.name)
        self.addCleanup(os.chdir, old_cwd)
        self.env = patch.dict(os.environ, {'OPENAI_API_KEY': DUMMY})
        self.env.start()
        self.addCleanup(self.env.stop)
        # Uma regressão que tente rede real falha imediatamente.
        self.network = patch.object(socket.socket, 'connect', side_effect=AssertionError('Rede externa proibida nos testes'))
        self.network.start()
        self.addCleanup(self.network.stop)
        self.scope = {}
        execute('configuration', self.scope)
        execute('helpers', self.scope)
        # A instalação é verificada separadamente com subprocess substituído.
        self.scope['_preparation_complete'] = True
        self.scope['display'] = lambda *args, **kwargs: None
        self.scope['Audio'] = lambda *args, **kwargs: None
        self.requests = []
        self.clients = []
        self.original_client = openai.OpenAI

    def colab(self, value=None, error=None, secret=DUMMY):
        colab = types.ModuleType('google.colab')
        def evaluate(code):
            self.eval_code = code
            if error:
                raise error
            return value if value is not None else captured()
        colab.output = types.SimpleNamespace(eval_js=evaluate)
        colab.userdata = types.SimpleNamespace(get=lambda name: secret)
        return patch.dict(sys.modules, {'google.colab': colab})

    def sdk(self, response=None, status=200, error=None):
        def handler(request):
            self.requests.append(request)
            if error:
                raise error
            data = completion() if response is None else response
            if status != 200:
                data = {'error': {'message': f'server echoed {DUMMY}', 'type': 'test_error', 'code': 'test'}}
            return httpx.Response(status, json=data)
        def build(**kwargs):
            client = self.original_client(
                **kwargs, base_url='https://api.openai.com/v1', max_retries=0,
                http_client=httpx.Client(transport=httpx.MockTransport(handler)),
            )
            self.clients.append(client)
            return client
        return patch.object(openai, 'OpenAI', side_effect=build)

    def whisper(self, text='Olá, assistente.', error=None):
        module = types.ModuleType('whisper')
        def load_model(name):
            self.loaded_model = name
            if error:
                raise error
            def transcribe(path, **kwargs):
                self.transcribe_call = (path, kwargs)
                return {'text': text}
            return types.SimpleNamespace(transcribe=transcribe)
        module.load_model = load_model
        return patch.dict(sys.modules, {'whisper': module})

    def tts(self, error=None, empty=False):
        import gtts
        def build(**kwargs):
            self.tts_kwargs = kwargs
            def save(path):
                Path(path).write_bytes(b'' if empty else b'ID3-offline-mp3')
                if error:
                    raise error
            return types.SimpleNamespace(save=save)
        return patch.object(gtts, 'gTTS', side_effect=build)

    def audio_file(self):
        p = Path('request.webm')
        p.write_bytes(b'fake-webm')
        return str(p.resolve())

    def test_schema_syntax_and_no_published_outputs(self):
        nbformat.validate(NOTEBOOK)
        for cell in NOTEBOOK.cells:
            if cell.cell_type == 'code':
                compile(cell.source, '<cell>', 'exec')
                self.assertEqual(cell.outputs, [])
                self.assertIsNone(cell.execution_count)
        self.assertNotIn('data:audio', json.dumps(NOTEBOOK))

    def test_configuration_preserves_approved_defaults_and_key(self):
        self.assertEqual(self.scope['SETTINGS'], {'language':'pt', 'record_seconds':5, 'whisper_model':'small', 'openai_model':'gpt-4'})
        self.assertEqual(os.environ['OPENAI_API_KEY'], DUMMY)

    def test_each_stage_without_setup_has_actionable_error(self):
        for tag in ('capture','transcribe','respond','speak'):
            with self.subTest(tag=tag), self.assertRaisesRegex(RuntimeError, 'configuração, preparação e funções'):
                execute(tag, {})

    def test_helpers_alone_do_not_bypass_preparation(self):
        self.scope['_preparation_complete'] = False
        for tag in ('capture','transcribe','respond','speak'):
            with self.subTest(tag=tag), self.assertRaisesRegex(RuntimeError,'preparação'):
                execute(tag,self.scope)

    def test_record_saves_actual_mime_and_returns_existing_path(self):
        for mime, suffix in [('audio/webm','.webm'),('audio/ogg','.ogg'),('audio/mp4','.m4a'),('audio/wav','.wav')]:
            with self.subTest(mime=mime), self.colab(captured(mime)):
                path = Path(self.scope['record']())
                self.assertTrue(path.is_file())
                self.assertEqual(path.suffix, suffix)
                self.assertEqual(path.read_bytes(), b'\x1a\x45\xdf\xa3fake-webm')
                self.assertEqual(self.eval_code, 'recordAudio(5000)')

    def test_record_accepts_codec_in_mime(self):
        with self.colab(captured('audio/webm;codecs=opus')):
            self.assertEqual(Path(self.scope['record']()).suffix, '.webm')

    def test_record_rejects_invalid_duration_before_capture(self):
        for sec in (0,-1,True,'5',float('inf'),float('nan')):
            with self.subTest(sec=sec), self.assertRaises(ValueError):
                self.scope['record'](sec)

    def test_record_rejects_malformed_empty_or_mismatched_audio(self):
        bad = [42, {'dataUrl':'invalid'}, captured(content=b''), captured('text/html'),
               {'mimeType':'audio/webm','dataUrl':'data:audio/webm;base64,!!!!'},
               {'mimeType':'audio/webm','dataUrl':'data:audio/ogg;base64,YQ=='},
               {'mimeType':'audio/webm','dataUrl':'data:audio/webm,YQ=='}]
        for data in bad:
            with self.subTest(data=data), self.colab(data), self.assertRaises(RuntimeError):
                self.scope['record']()
        self.assertEqual(list(Path('.').glob('request_audio.*')), [])

    def test_record_reports_denied_permission_without_external_details(self):
        with self.colab(error=RuntimeError(DUMMY)), self.assertRaisesRegex(RuntimeError,'permissão') as caught:
            self.scope['record']()
        self.assertNotIn(DUMMY, str(caught.exception))

    def test_record_disk_failure_is_actionable(self):
        with self.colab(), patch.object(Path,'write_bytes',side_effect=OSError()), self.assertRaisesRegex(RuntimeError,'salvar'):
            self.scope['record']()

    def test_whisper_parameters_and_result(self):
        path = self.audio_file()
        with self.whisper('  Olá!  '), patch('shutil.which',return_value='/usr/bin/ffmpeg'):
            self.assertEqual(self.scope['transcribe_audio'](path), 'Olá!')
        self.assertEqual(self.loaded_model,'small')
        self.assertEqual(self.transcribe_call,(path,{'fp16':False,'language':'pt'}))

    def test_whisper_missing_or_empty_file(self):
        Path('empty.webm').touch()
        for value in (None,'missing.webm','empty.webm'):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                self.scope['transcribe_audio'](value)

    def test_whisper_requires_ffmpeg_before_model_load(self):
        with patch('shutil.which',return_value=None), self.assertRaisesRegex(RuntimeError,'FFmpeg'):
            self.scope['transcribe_audio'](self.audio_file())

    def test_whisper_rejects_empty_transcription(self):
        with self.whisper('  '), self.assertRaisesRegex(RuntimeError,'Nenhuma fala'):
            self.scope['transcribe_audio'](self.audio_file())

    def test_whisper_load_error_is_actionable(self):
        with self.whisper(error=RuntimeError('download failed')), self.assertRaisesRegex(RuntimeError,'Falha na transcrição'):
            self.scope['transcribe_audio'](self.audio_file())

    def test_key_from_environment_is_not_overwritten(self):
        self.assertEqual(self.scope['read_api_key'](), DUMMY)
        self.assertEqual(os.environ['OPENAI_API_KEY'],DUMMY)

    def test_key_from_colab_secret(self):
        with patch.dict(os.environ,{'OPENAI_API_KEY':''}), self.colab(secret=DUMMY):
            self.assertEqual(self.scope['read_api_key'](),DUMMY)
            self.assertEqual(os.environ['OPENAI_API_KEY'],'')

    def test_key_rejects_placeholder_and_empty_secret(self):
        for key in ('API KEY AQUI','your_api_key','sk-placeholder'):
            with self.subTest(key=key), patch.dict(os.environ,{'OPENAI_API_KEY':key}), self.assertRaises(RuntimeError):
                self.scope['read_api_key']()
        with patch.dict(os.environ,{'OPENAI_API_KEY':''}), self.colab(secret=None), self.assertRaises(RuntimeError):
            self.scope['read_api_key']()

    def test_key_secret_access_error_is_not_exposed(self):
        with patch.dict(os.environ,{'OPENAI_API_KEY':''}), self.colab():
            sys.modules['google.colab'].userdata.get = lambda name: (_ for _ in ()).throw(RuntimeError(DUMMY))
            with self.assertRaisesRegex(RuntimeError,'Segredos') as caught:
                self.scope['read_api_key']()
            self.assertNotIn(DUMMY,str(caught.exception))

    def test_real_sdk_uses_chat_completions_and_original_model(self):
        with self.sdk():
            self.assertEqual(self.scope['ask_chatgpt']('  Olá!  '),'Resposta em português.')
        self.assertEqual(len(self.requests),1)
        self.assertEqual(str(self.requests[0].url),'https://api.openai.com/v1/chat/completions')
        self.assertEqual(json.loads(self.requests[0].content),{'model':'gpt-4','messages':[{'role':'user','content':'Olá!'}]})
        self.assertTrue(all(c.is_closed() for c in self.clients))

    def test_sdk_preserves_explicit_model_argument(self):
        with self.sdk():
            self.scope['ask_chatgpt']('Olá',model_name='explicit-test-model')
        self.assertEqual(json.loads(self.requests[0].content)['model'],'explicit-test-model')

    def test_empty_transcription_never_constructs_client(self):
        with patch.object(openai,'OpenAI') as client:
            for text in (None,'','   ',42):
                with self.subTest(text=text), self.assertRaisesRegex(RuntimeError,'transcrição'):
                    self.scope['ask_chatgpt'](text)
            client.assert_not_called()

    def test_sdk_status_errors_are_redacted_and_close_client(self):
        for status,fragment in [(401,'autenticação'),(403,'permissão'),(429,'cota'),(400,'solicitação'),(500,'solicitação')]:
            with self.subTest(status=status), self.sdk(status=status), self.assertRaisesRegex(RuntimeError,fragment) as caught:
                self.scope['ask_chatgpt']('Olá')
            self.assertNotIn(DUMMY,str(caught.exception))
            self.assertTrue(self.clients[-1].is_closed())

    def test_sdk_connection_and_timeout_errors(self):
        for error,fragment in [(httpx.ConnectError(DUMMY),'conectar'),(httpx.ReadTimeout(DUMMY),'demorou')]:
            with self.subTest(error=type(error).__name__), self.sdk(error=error), self.assertRaisesRegex(RuntimeError,fragment) as caught:
                self.scope['ask_chatgpt']('Olá')
            self.assertNotIn(DUMMY,str(caught.exception))
            self.assertTrue(self.clients[-1].is_closed())

    def test_sdk_rejects_empty_or_incomplete_responses(self):
        for data in [completion(None),completion('   '),completion('partial','length'),completion(None,'content_filter'),{'id':'x','object':'chat.completion','created':0,'model':'gpt-4','choices':[]}]:
            with self.subTest(response=data), self.sdk(response=data), self.assertRaises(RuntimeError):
                self.scope['ask_chatgpt']('Olá')

    def test_tts_writes_mp3_atomically_with_original_language(self):
        with self.tts():
            path = Path(self.scope['synthesize_speech'](' Olá '))
        self.assertEqual(path.suffix,'.mp3')
        self.assertEqual(path.read_bytes(),b'ID3-offline-mp3')
        self.assertEqual(self.tts_kwargs,{'text':'Olá','lang':'pt','slow':False,'timeout':(10,60)})
        self.assertEqual(list(Path('.').glob('.response-*')),[])

    def test_tts_real_library_writes_stream_without_google(self):
        from gtts import gTTS
        with patch.object(gTTS,'stream',return_value=iter([b'ID3-real-library-offline-stream'])):
            path = Path(self.scope['synthesize_speech']('Olá'))
        self.assertEqual(path.read_bytes(),b'ID3-real-library-offline-stream')
        self.assertEqual(path.suffix,'.mp3')

    def test_tts_rejects_empty_input_or_wrong_suffix(self):
        with patch('gtts.gTTS') as service:
            for text in (None,'   ',42):
                with self.subTest(text=text), self.assertRaises(RuntimeError):
                    self.scope['synthesize_speech'](text)
            with self.assertRaises(ValueError):
                self.scope['synthesize_speech']('Olá',destination='response.wav')
            service.assert_not_called()

    def test_tts_failure_cleans_partial_file_and_preserves_previous_artifact(self):
        from gtts import gTTSError
        Path('response_audio.mp3').write_bytes(b'previous')
        with self.tts(error=gTTSError('offline')), self.assertRaisesRegex(RuntimeError,'Google'):
            self.scope['synthesize_speech']('Olá')
        self.assertEqual(Path('response_audio.mp3').read_bytes(),b'previous')
        self.assertEqual(list(Path('.').glob('.response-*')),[])

    def test_tts_empty_result_is_not_published(self):
        with self.tts(empty=True), self.assertRaisesRegex(RuntimeError,'vazio'):
            self.scope['synthesize_speech']('Olá')
        self.assertFalse(Path('response_audio.mp3').exists())
        self.assertEqual(list(Path('.').glob('.response-*')),[])

    def test_tts_disk_error_is_actionable(self):
        with self.tts(), patch('tempfile.NamedTemporaryFile',side_effect=OSError()), self.assertRaisesRegex(RuntimeError,'salvar'):
            self.scope['synthesize_speech']('Olá')

    def test_complete_cells_with_real_sdk_and_simulated_services(self):
        with self.colab(), self.whisper(), self.sdk(), self.tts():
            for tag in ('capture','transcribe','respond','speak'):
                execute(tag,self.scope)
        self.assertEqual(Path(self.scope['record_file']).suffix,'.webm')
        self.assertEqual(self.scope['transcription'],'Olá, assistente.')
        self.assertEqual(self.scope['chatgpt_response'],'Resposta em português.')
        self.assertEqual(Path(self.scope['response_audio']).read_bytes(),b'ID3-offline-mp3')

    def test_failed_stages_invalidate_all_downstream_values(self):
        mapping = {
            'capture':('record_file','transcription','chatgpt_response','response_audio'),
            'transcribe':('transcription','chatgpt_response','response_audio'),
            'respond':('chatgpt_response','response_audio'),
            'speak':('response_audio',),
        }
        functions = {'capture':'record','transcribe':'transcribe_audio','respond':'ask_chatgpt','speak':'synthesize_speech'}
        for tag,cleared in mapping.items():
            with self.subTest(tag=tag):
                for key in mapping['capture']:
                    self.scope[key] = 'previous-value'
                # Trocar só a função: patch.dict restauraria também o estado
                # alterado pela célula, escondendo a invalidação que queremos medir.
                original = self.scope[functions[tag]]
                self.scope[functions[tag]] = lambda *args: (_ for _ in ()).throw(RuntimeError('forced failure'))
                try:
                    with self.assertRaises(RuntimeError):
                        execute(tag,self.scope)
                finally:
                    self.scope[functions[tag]] = original
                for key in cleared:
                    self.assertIsNone(self.scope[key],f'{tag}: {key}')

    def test_out_of_order_steps_do_not_call_external_services(self):
        for tag,fragment in [('transcribe','gravação'),('respond','transcrição'),('speak','resposta válida')]:
            with self.subTest(tag=tag), self.assertRaisesRegex(RuntimeError,fragment):
                execute(tag,self.scope)

    def test_setup_rejects_non_colab_before_installing(self):
        with patch.dict(sys.modules,{'google.colab':None}), patch('subprocess.run') as run:
            with self.assertRaisesRegex(RuntimeError,'Google Colab'):
                execute('setup',{})
            run.assert_not_called()

    def test_setup_rejects_missing_ffmpeg_before_installing(self):
        with self.colab(), patch('shutil.which',return_value=None), patch('subprocess.run') as run:
            with self.assertRaisesRegex(RuntimeError,'FFmpeg'):
                execute('setup',{})
            run.assert_not_called()

    def test_setup_install_failure_stops_preparation(self):
        import subprocess
        with self.colab(), patch('subprocess.run',side_effect=subprocess.CalledProcessError(1,'pip')):
            with self.assertRaises(subprocess.CalledProcessError):
                execute('setup',{})

    def test_setup_records_preparation_and_reports_conflicts(self):
        import subprocess
        for status in (0,1):
            scope = {'_assistant_ready':True}
            check_result = subprocess.CompletedProcess(['pip','check'],status,stdout='dependency conflict' if status else '')
            with self.subTest(pip_check_status=status), self.colab(), patch('subprocess.run',side_effect=[subprocess.CompletedProcess('pip',0),check_result]) as run:
                execute('setup',scope)
            self.assertTrue(scope['_preparation_complete'])
            self.assertFalse(scope['_assistant_ready'])
            self.assertTrue(run.call_args_list[0].kwargs['check'])

    def test_setup_failure_revokes_previous_preparation(self):
        scope = {'_preparation_complete':True,'_assistant_ready':True}
        with self.colab(), patch('shutil.which',return_value=None), self.assertRaises(RuntimeError):
            execute('setup',scope)
        self.assertFalse(scope['_preparation_complete'])
        self.assertFalse(scope['_assistant_ready'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
