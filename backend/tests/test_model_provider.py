from types import SimpleNamespace
from app.services.ai import provider_options


def test_provider_error_is_classified_without_exposing_upstream_body():
    import httpx
    from unittest.mock import patch,MagicMock
    from app.services.ai import complete,ModelServiceError
    model=SimpleNamespace(id='test',model='qwen3.8-max',base_url='https://dashscope.aliyuncs.com/compatible-mode/v1')
    client=MagicMock();client.post.return_value=httpx.Response(400,json={'error':{'code':'Arrearage','message':'untrusted sensitive response'}})
    with patch('app.services.ai.headers',return_value={}),patch('app.services.ai.httpx.Client') as factory:
        factory.return_value.__enter__.return_value=client
        try: complete(MagicMock(),'test',[{'role':'user','content':'synthetic test'}],config=model)
        except ModelServiceError as error:
            assert error.code=='Arrearage' and '欠费' in str(error)
            assert 'untrusted sensitive response' not in str(error)
        else: raise AssertionError('provider error was not classified')
        factory.assert_called_once_with(timeout=httpx.Timeout(300), follow_redirects=False)
        factory.reset_mock()
        with patch.object(client, 'post', return_value=httpx.Response(200, json={
            'choices': [{'message': {'content': 'completed'}}],
        })):
            content, _ = complete(MagicMock(), 'test', [], config=model, read_timeout=None)
        assert content == 'completed'
        factory.assert_called_once_with(timeout=httpx.Timeout(300, read=None), follow_redirects=False)


def test_qwen38_official_json_and_stream_compatibility():
    for base in ['https://dashscope.aliyuncs.com/compatible-mode/v1','https://dashscope-intl.aliyuncs.com/compatible-mode/v1','https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1']:
        assert provider_options(SimpleNamespace(base_url=base,model='qwen3.8-max'))=={'enable_thinking':False}
    assert provider_options(SimpleNamespace(base_url='https://other.example/v1',model='qwen3.8-max'))=={}
    assert provider_options(SimpleNamespace(base_url='https://dashscope.aliyuncs.com/compatible-mode/v1',model='unrelated-model'))=={}


def test_model_not_found_is_actionable_and_case_sensitive_ids_are_preserved():
    import pytest
    from pydantic import ValidationError
    from app.schemas import ModelInput
    from app.services.ai import ModelServiceError
    for code in ['model_not_found','ModelNotFound','Model.NotFound']:
        text=str(ModelServiceError(404,code))
        assert '大小写' in text and '工作空间' in text and '暂时不可用' not in text
    config=ModelInput(name='显示名称',base_url='https://example.invalid/v1',model='  MyDeployment-ABC  ',api_key='test-only')
    assert config.model=='MyDeployment-ABC'
    with pytest.raises(ValidationError): ModelInput(name='test',base_url='https://example.invalid/v1',model='  ',api_key='test-only')
