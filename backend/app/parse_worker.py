import json, sys
from pathlib import Path
from .services.files import WordConversionError, parse_file

if sys.platform!='win32':
    import resource
    resource.setrlimit(resource.RLIMIT_AS,(1024*1024*1024,1024*1024*1024))
    resource.setrlimit(resource.RLIMIT_CPU,(60,60))

if __name__=='__main__':
    path, suffix = Path(sys.argv[1]), sys.argv[2]
    try:
        if sys.argv[3:4] == ['preview']:
            from .services.source_preview import preview_file
            result = preview_file(path,suffix,*map(int,sys.argv[4:]))
        else:
            result = parse_file(path,suffix)
    except WordConversionError as error:
        sys.exit(str(error))
    print(json.dumps(result,ensure_ascii=False))
