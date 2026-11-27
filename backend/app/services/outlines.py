from .manuscript import heading_key

MAX_OUTLINE_ITEMS=100
MAX_OUTLINE_TITLE_LENGTH=500


def normalize_outline(value) -> list[str]:
    if isinstance(value,str):
        value=value.splitlines()
    if not isinstance(value,list) or any(not isinstance(item,str) for item in value):
        raise ValueError('提纲应为每行一个标题的文本，或标题字符串列表')
    titles=[line.strip().lstrip('\ufeff') for item in value for line in item.splitlines() if line.strip()]
    if not titles:
        raise ValueError('提纲至少需要一个非空标题')
    if len(titles)>MAX_OUTLINE_ITEMS:
        raise ValueError(f'提纲共有 {len(titles)} 项，最多支持 {MAX_OUTLINE_ITEMS} 项，请合并部分章节后重试')
    for index,title in enumerate(titles,1):
        if len(title)>MAX_OUTLINE_TITLE_LENGTH:
            raise ValueError(f'提纲第 {index} 项超过 {MAX_OUTLINE_TITLE_LENGTH} 字，请将说明移入正文')
    if sum(map(len,titles))>20000:
        raise ValueError('提纲总长度超过 20000 字，请精简后重试')
    seen=set();unique=[]
    for title in titles:
        key=heading_key(title)
        if key not in seen: unique.append(title);seen.add(key)
    return unique
