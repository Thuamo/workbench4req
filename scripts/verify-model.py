"""Minimal real provider checks. No business evidence, key or raw provider errors are logged."""
import argparse, json, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
sys.stdout.reconfigure(encoding='utf-8')
import httpx
from app.db import SessionLocal
from app.services.ai import model_config, headers, provider_options


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--mode',choices=['plain','json','stream'],default='plain')
    args=parser.parse_args()
    with SessionLocal() as db:
        config=model_config(db)
        url=config.base_url.rstrip('/')+'/chat/completions'
        auth=headers(config)
        model=config.model
        options=provider_options(config)
    body={'model':model,'messages':[{'role':'user','content':'请仅回复 OK。'}],'max_tokens':32,**options}
    if args.mode=='json':
        body['messages']=[{'role':'user','content':'请仅输出 JSON 对象 {"ok":true}。'}]
        body['response_format']={'type':'json_object'}
    result={'model':model,'mode':args.mode}
    try:
        with httpx.Client(timeout=40,follow_redirects=False) as client:
            if args.mode=='stream':
                body.update(stream=True,stream_options={'include_usage':True})
                text=''
                with client.stream('POST',url,headers=auth,json=body) as response:
                    result['http_status']=response.status_code
                    if response.status_code>=400:
                        result.update(ok=False,error='provider_http_error')
                    else:
                        for line in response.iter_lines():
                            if not line.startswith('data: '):
                                continue
                            if line[6:]=='[DONE]':
                                break
                            data=json.loads(line[6:])
                            choices=data.get('choices',[])
                            if choices:
                                text+=choices[0].get('delta',{}).get('content') or ''
                        result.update(ok=bool(text.strip()),received_text=bool(text.strip()))
            else:
                response=client.post(url,headers=auth,json=body)
                result['http_status']=response.status_code
                if response.status_code>=400:
                    try:
                        code=response.json().get('error',{}).get('code')
                    except (ValueError,AttributeError):
                        code=None
                    result.update(ok=False,error='provider_http_error',provider_code=code if isinstance(code,str) and len(code)<100 else None)
                else:
                    data=response.json()
                    content=data['choices'][0]['message'].get('content') or ''
                    result.update(ok=bool(content.strip()),received_text=bool(content.strip()),usage=data.get('usage',{}))
                    if args.mode=='json':
                        result['valid_json']=isinstance(json.loads(content),dict)
    except httpx.TransportError as error:
        result.update(ok=False,error_type=type(error).__name__)
    print(json.dumps(result,ensure_ascii=False))
    return 0 if result.get('ok') else 1


if __name__=='__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({'ok':False,'error_type':type(error).__name__}))
        raise SystemExit(1)
