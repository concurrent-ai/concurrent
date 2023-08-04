import gunicorn.app.base
import json
import mlflow
import os

def number_of_workers():
    return 1

def init_pipeline():
    model_uri='/root/model'
    pipeline = mlflow.transformers.load_model(model_uri, None, return_type='pipeline', device=None)
    print(f"init_pipeline: Created pipeline={pipeline}", flush=True)
    ot = os.getenv('OPTIMIZER_TECHNOLOGY', 'no-optimizer')
    print(f"init_pipeline: Found env var OPTIMIZER_TECHNOLOGY={ot}", flush=True)
    if ot == 'deepspeed':
        import deepspeed
        import torch
        local_rank = int(os.getenv('LOCAL_RANK', '0'))
        world_size = int(os.getenv('WORLD_SIZE', '1'))
        print(f"Done importing deepspeed. Calling init_inference. local_rank={local_rank}, world_size={world_size}", flush=True)
        pipeline.model = deepspeed.init_inference(
            pipeline.model,
            mp_size=world_size,
            dtype=torch.float
        )
        pipeline.device = torch.device(f'cuda:{local_rank}')
    print(f"init_pipeline: After processing env var OPTIMIZER_TECHNOLOGY. pipeline={pipeline}", flush=True)
    global gpipeline
    gpipeline = pipeline

def handler_app(environ, start_response):
    global gpipeline
    print(f"infer: Entered. environ={environ}, gpipeline={gpipeline}", flush=True)
    if not gpipeline:
        return bad_request_return(b"Error. Pipeline not available")
    try:
        request_body_size = int(environ.get('CONTENT_LENGTH', 0))
    except (ValueError):
        return bad_request_return(b"Error. Content length not available")
    req_str = bytes.decode(environ['wsgi.input'].read(request_body_size), 'utf-8')
    print('>>>>>>>>>>>>>>>>>>>1', flush=True)
    print(req_str, flush=True)
    print('<<<<<<<<<<<<<<<<<<<', flush=True)
    req = json.loads(req_str)
    print('>>>>>>>>>>>>>>>>>>>2', flush=True)
    print(json.dumps(req), flush=True)

    inp_columns = req['columns']
    for i in range(len(inp_columns)):
        print(f"column{i}: {inp_columns[i]}", flush=True)
        if inp_columns[i] == 'text':
            text_index = i
    model_input = []
    for d in req['data']:
        model_input.append(d[text_index])

    print(f"model_input={model_input}", flush=True)
    output = gpipeline(model_input)
    print(f'output={output}', flush=True)
    data = bytes(json.dumps(output), 'utf-8')
    #data = b"Hello, World!\n"
    start_response("200 OK", [
                ("Content-Type", "text/plain"),
                ("Content-Length", str(len(data)))
            ])
    return iter([data])

class StandaloneApplication(gunicorn.app.base.BaseApplication):
    def __init__(self, app, options=None):
        self.options = options or {}
        self.application = app
        super().__init__()

    def load_config(self):
        config = {key: value for key, value in self.options.items()
                  if key in self.cfg.settings and value is not None}
        for key, value in config.items():
            self.cfg.set(key.lower(), value)

    def load(self):
        return self.application


if __name__ == '__main__':
    options = {
        'bind': '%s:%s' % ('0.0.0.0', '8080'),
        'workers': number_of_workers(),
    }
    global gpipeline
    gpipeline = None
    print(f"main: Before init_pipline", flush=True)
    init_pipeline()
    print(f"main: After init_pipline. gpipeline={gpipeline}", flush=True)
    StandaloneApplication(handler_app, options).run()
