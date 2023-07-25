import gunicorn.app.base
import json
import mlflow
import os

def number_of_workers():
    return 1

def handler_app(environ, start_response):
    print(f"infer: Entered. environ={environ}")
    try:
        request_body_size = int(environ.get('CONTENT_LENGTH', 0))
    except (ValueError):
        return bad_request_return(b"Error. Content length not available")
    req_str = bytes.decode(environ['wsgi.input'].read(request_body_size), 'utf-8')
    print('>>>>>>>>>>>>>>>>>>>1')
    print(req_str)
    print('<<<<<<<<<<<<<<<<<<<')
    req = json.loads(req_str)
    print('>>>>>>>>>>>>>>>>>>>2')
    print(json.dumps(req))

    inp_columns = req['columns']
    for i in range(len(inp_columns)):
        print(f"column{i}: {inp_columns[i]}")
        if inp_columns[i] == 'text':
            text_index = i
    model_input = []
    for d in req['data']:
        model_input.append(d[text_index])

    print(f"model_input={model_input}")
    model_uri='/root/model'
    pipeline = mlflow.transformers.load_model(model_uri, None, return_type='pipeline', device=None)
    print(f"before deepspeed: pipeline={pipeline}")
    ot = os.getenv('OPTIMIZER_TECHNOLOGY', 'no-optimizer')
    print(f"Found env var OPTIMIZER_TECHNOLOGY={ot}")
    if ot == 'deepspeed':
        import deepspeed
        local_rank = int(os.getenv('LOCAL_RANK', '0'))
        world_size = int(os.getenv('WORLD_SIZE', '1'))
        print(f"Done importing deepspeed. Calling init_inference")
        pipeline.model = deepspeed.init_inference(
            pipeline.model,
            mp_size=world_size,
            dtype=torch.float
        )
        pipeline.device = torch.device(f'cuda:{local_rank}')
    print(f"after deepspeed: pipeline={pipeline}")

    output = pipeline(model_input)
    print(f'output={output}')
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
    StandaloneApplication(handler_app, options).run()
