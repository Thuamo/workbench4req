from app.services.manuscript import assemble_sections,clean_rich_document,strip_citation_ids
from app.services.richtext import rich_content
from app.services.outlines import normalize_outline
from app.services.agents import document
from unittest.mock import patch

def test_parent_does_not_repeat_separately_generated_children():
    text=assemble_sections([
        {'title':'1 背景与目标','content':'# 1 背景与目标\n父章节概述\n## 1.1 背景\n父章节里重复生成的背景\n## 1.2 目标\n父章节里重复生成的目标'},
        {'title':'1.1 背景','content':'## 1.1 背景\n实际背景[citation_id: abc-123]'},
        {'title':'1.2 目标','content':'#### 1.2 目标\n实际目标'},
        {'title':'2 方案','content':'## 2 方案\n方案内容\n### 未单独生成的补充\n保留此补充'}])
    assert text.count('# 1 背景与目标')==1
    assert text.count('## 1.1 背景')==1 and text.count('## 1.2 目标')==1
    assert '父章节里重复生成的' not in text
    assert '实际背景' in text and '实际目标' in text and '保留此补充' in text
    assert 'citation_id' not in text

def test_rich_cleanup_retains_every_business_paragraph_and_source_record():
    def h(level,text): return {'type':'heading','attrs':{'level':level},'content':[{'type':'text','text':text}]}
    original={'type':'doc','content':[h(1,'1 背景'),h(2,'1 背景'),{'type':'paragraph','content':[{'type':'text','text':'保留人工修改[citation_'},{'type':'text','text':'id: uuid-1]后续内容','marks':[{'type':'bold'}]}]},h(1,'1.1 说明'),h(3,'1.1 说明'),{'type':'paragraph','content':[{'type':'text','text':'第二段业务规则'}]}]}
    tree,issues=clean_rich_document(original)
    assert issues=={'duplicate_headings':2,'citation_markers':1}
    _,text=rich_content(tree)
    assert '保留人工修改' in text and '后续内容' in text and '第二段业务规则' in text
    assert 'citation_id' not in text and 'uuid-1' not in text
    assert [n['attrs']['level'] for n in tree['content'] if n['type']=='heading']==[1,2]
    assert len(original['content'])==6
    assert strip_citation_ids('接口ID ABC、[1]、[citation_id: UUID]')=='接口ID ABC、[1]、'

def test_same_unnumbered_heading_in_different_chapters_is_preserved():
    def h(level,text):return {'type':'heading','attrs':{'level':level},'content':[{'type':'text','text':text}]}
    tree,issues=clean_rich_document({'type':'doc','content':[h(1,'1 第一章'),h(2,'处理逻辑'),h(1,'2 第二章'),h(2,'处理逻辑')]})
    assert issues['duplicate_headings']==0 and len(tree['content'])==4


def test_plain_and_bold_child_titles_do_not_duplicate_bodies():
    text=assemble_sections([
        {'title':'1 需求背景与目标','content':'父章说明\n1.1 需求背景\n重复背景\n**1.2 需求目标**\n重复目标\n1. 不能重复的目标'},
        {'title':'1.1 需求背景','content':'1.1需求背景\n正式背景'},
        {'title':'1.2 需求目标','content':'**1.2 需求目标**\n1. 建立查询链路\n2. 完善数据供给'},
        {'title':'2 方案','content':'1.1 需求背景中的字段应保留\n```text\n1.1 需求背景\n代码示例\n```\n| 1.2 需求目标 | 字段 |'}])
    assert '重复背景' not in text and '重复目标' not in text
    assert text.count('正式背景')==1 and text.count('建立查询链路')==1
    assert text.count('## 1.1 需求背景')==1 and text.count('## 1.2 需求目标')==1
    assert '1.1 需求背景中的字段应保留' in text and '代码示例' in text
    assert '| 1.2 需求目标 | 字段 |' in text


def test_generation_normalizes_outline_and_stores_only_direct_body():
    outline=['1 需求背景与目标','1.1 需求背景','1.2 需求目标','**1.1 需求背景**']
    assert normalize_outline(outline)==outline[:3]
    def answer(state,agent,instruction):
        if '编写“1 需求背景与目标”' in instruction:
            return {'answer':'1.1 需求背景\n父章重复背景\n1.2 需求目标\n父章重复目标','citations':[]}
        return {'answer':'独立子章正文','citations':[]}
    with patch('app.services.agents.ask',side_effect=answer) as model:
        sections=document({'outline':outline})['sections']
    assert model.call_count==3 and len(sections)==3
    assert sections[0]['content']==''
    assert all('父章重复' not in section['content'] for section in sections)


def test_rich_cleanup_removes_identical_plain_heading_sections_only():
    def p(text):return {'type':'paragraph','content':[{'type':'text','text':text}]}
    def h(text):return {'type':'heading','attrs':{'level':2},'content':[{'type':'text','text':text}]}
    rules={'type':'orderedList','attrs':{'start':1},'content':[{'type':'listItem','content':[p('建立查询链路')]},{'type':'listItem','content':[p('提供数据')]}]}
    original={'type':'doc','content':[h('1 需求背景与目标'),p('1.1 需求背景'),p('背景正文'),p('1.2 需求目标'),rules,h('1.1 需求背景'),p('背景正文'),h('1.2 需求目标'),rules,h('2 补充'),p('背景正文')]}
    cleaned,issues=clean_rich_document(original)
    _,text=rich_content(cleaned)
    assert issues['duplicate_sections']==2
    assert text.count('背景正文')==2  # Same paragraph in a different chapter is intentional.
    assert text.count('建立查询链路')==1 and text.count('1.1 需求背景')==1
    assert len(original['content'])==11
    changed={'type':'doc','content':[h('1.1 规则'),p('旧规则'),h('1.1 规则'),p('人工补充的新规则')]}
    result,issues=clean_rich_document(changed)
    assert 'duplicate_sections' not in issues
    assert '旧规则' in rich_content(result)[1] and '人工补充的新规则' in rich_content(result)[1]


def test_cleanup_preserves_distinct_list_numbering_and_table_content():
    def p(text):return {'type':'paragraph','content':[{'type':'text','text':text}]}
    def h():return {'type':'heading','attrs':{'level':2},'content':[{'type':'text','text':'1.1 规则'}]}
    def ordered(start):return {'type':'orderedList','attrs':{'start':start},'content':[{'type':'listItem','content':[p('相同文字')]}]}
    value={'type':'doc','content':[h(),ordered(1),h(),ordered(2)]}
    result,issues=clean_rich_document(value)
    assert 'duplicate_sections' not in issues
    assert sum(n['type']=='orderedList' for n in result['content'])==2


def test_plain_title_soft_break_is_detected_without_changing_distinct_rules():
    h={'type':'heading','attrs':{'level':2},'content':[{'type':'text','text':'1.1 需求背景'}]}
    for inline in [[{'type':'text','text':'1.1 需求背景\n相同正文'}],
                   [{'type':'text','text':'1.1 需求背景','marks':[{'type':'bold'}]},{'type':'hardBreak'},{'type':'text','text':'相同正文'}]]:
        value={'type':'doc','content':[{'type':'paragraph','content':inline},h,{'type':'paragraph','content':[{'type':'text','text':'相同正文'}]}]}
        result,issues=clean_rich_document(value)
        assert issues['duplicate_sections']==1
        assert rich_content(result)[1].count('相同正文')==1
