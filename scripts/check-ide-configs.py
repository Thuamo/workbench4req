"""Read-only validation of shared editor launch paths; does not start services."""
import importlib, json, sys
from pathlib import Path
import xml.etree.ElementTree as ET

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'backend'))
configs={}
for file in sorted((root/'.run').glob('*.run.xml')):
    config=ET.parse(file).getroot().find('configuration')
    assert config is not None,file
    configs[config.attrib['name']]=config
    if config.attrib['type']=='PythonConfigurationType':
        options={item.attrib['name']:item.attrib['value'] for item in config.findall('option')}
        assert options['WORKING_DIRECTORY']=='$PROJECT_DIR$',file
        interpreter=Path(options['SDK_HOME'].replace('$PROJECT_DIR$',str(root)))
        assert interpreter.is_file(),interpreter
        assert options['MODULE_MODE']=='true',file
        environment={item.attrib['name']:item.attrib['value'] for item in config.findall('./envs/env')}
        assert environment['PYTHONPATH']=='$PROJECT_DIR$/backend',file
        importlib.import_module(options['SCRIPT_NAME'])
    elif config.attrib['type']=='js.build_tools.npm':
        package=config.find('package-json').attrib['value'].replace('$PROJECT_DIR$',str(root))
        data=json.loads(Path(package).read_text(encoding='utf-8'))
        assert 'dev' in data['scripts']
assert set(configs)=={'Workbench API','Workbench Worker','Workbench Frontend','Workbench Migrate','Workbench Seed','Workbench All'}
for target in configs['Workbench All'].findall('toRun'):
    assert target.attrib['name'] in configs
    assert target.attrib['type']==configs[target.attrib['name']].attrib['type']
launch=json.loads((root/'.vscode/launch.json').read_text(encoding='utf-8'))
names={config['name'] for config in launch['configurations']}
assert names=={'Workbench API','Workbench Worker','Workbench Frontend'}
assert set(launch['compounds'][0]['configurations'])==names
assert (root/'frontend/node_modules/next/dist/bin/next').is_file()
for file in ['settings.json','extensions.json']:
    json.loads((root/'.vscode'/file).read_text(encoding='utf-8'))
from app.config import settings
from sqlalchemy.engine import make_url
database=make_url(settings.database_url).database
assert database and Path(database).is_file()
print(json.dumps({'pycharm_configurations':len(configs),'vscode_configurations':len(names),'python_modules_imported':True,'next_entry_exists':True,'database_file':str(Path(database).resolve()),'services_started':False},ensure_ascii=False))
