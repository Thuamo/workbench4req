from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, model_validator,field_validator
from .password_policy import MIN_PASSWORD_LENGTH, MAX_PASSWORD_LENGTH


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Register(Strict):
    username: str = Field(min_length=3, max_length=80, pattern=r'^[\w.-]+$')
    display_name: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)
    confirm_password: str

    @model_validator(mode='after')
    def passwords_match(self):
        if self.password != self.confirm_password:
            raise ValueError('两次密码不一致')
        return self


class Login(Strict):
    username: str = Field(max_length=80)
    password: str = Field(max_length=MAX_PASSWORD_LENGTH)


class AdminRegister(Register):
    role: Literal['requirement_member', 'qa_member', 'reviewer', 'super_admin', 'development_member'] = 'requirement_member'


class PasswordChange(Strict):
    current_password: str
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)


class BaseInput(Strict):
    name: str = Field(min_length=1, max_length=200)
    description: str = ''
    public: bool = True
    member_ids: list[str] = Field(default_factory=list)
    enabled: bool = True


class FolderInput(Strict):
    name: str = Field(min_length=1, max_length=200)
    parent_id: str | None = None


class VersionInput(Strict):
    label: str = Field(min_length=1, max_length=80)
    content: str | None = Field(default=None, max_length=2000000)
    source_version_id: str | None = None
    change_note: str = ''


class EditVersion(Strict):
    content: str = Field(max_length=2000000)
    expected_revision: int


class DocumentMetadata(Strict):
    title: str = Field(min_length=1,max_length=300)
    folder_id: str | None = None
    requirement_id: str | None = None
    kind: Literal['reference','business','specification','template'] = 'reference'


class Submit(Strict):
    reviewer_ids: list[str] = Field(min_length=1, max_length=20)
    note: str = Field(default='',max_length=10000)


class BatchSubmit(Submit):
    version_ids: list[str] = Field(min_length=1, max_length=50)
    expected_revisions: dict[str, int] = Field(default_factory=dict)
    expected_pack_id: str | None = None


class Decision(Strict):
    decision: Literal['approved', 'returned']
    comment: str = Field(default='', max_length=10000)


class ReviewDecisionItem(Strict):
    task_id: str = Field(min_length=1,max_length=36)
    locked_hash: str = Field(pattern=r'^[0-9a-f]{64}$')


class BatchDecision(Decision):
    items: list[ReviewDecisionItem] = Field(min_length=1,max_length=50)


class SnapshotInput(Strict):
    name: str = Field(min_length=1, max_length=100)
    note: str = ''


class RequirementInput(Strict):
    number: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=300)
    description: str = ''
    tags: dict[str, list[str]] = Field(default_factory=dict)
    acceptance: str = ''
    state: Literal['draft', 'clarifying', 'confirmed', 'specified', 'published'] = 'draft'
    source_version_id: str | None = None


class TaskInput(Strict):
    fields: dict = Field(default_factory=dict)
    status: Literal['pending','in_progress','completed','not_needed'] = 'pending'
    requirement_id: str | None = None
    expected_revision: int | None = None


class RequirementWizardInput(Strict):
    requirement: RequirementInput
    initialize_tasks: bool = True
    create_clarification: bool = True


class QuestionInput(Strict):
    description: str = Field(min_length=1)
    category: str = '业务规则'
    task_id: str | None = None
    requirement_id: str | None = None
    reason: str = ''
    evidence: dict = Field(default_factory=dict)
    target: str = ''
    feedback: str = ''
    conclusion: str = ''
    status: Literal['open','answered','confirmed','rejected'] = 'open'


class ModelInput(Strict):
    name: str
    base_url: str = Field(pattern=r'^https?://')
    model: str = Field(min_length=1,max_length=200)
    api_key: str = Field(min_length=1)
    kind: Literal['chat','embedding'] = 'chat'

    @field_validator('model',mode='before')
    @classmethod
    def trim_model_id(cls,value):
        # Deployment IDs and other vendors can be case-sensitive. Never lowercase all IDs.
        return value.strip() if isinstance(value,str) else value


class SkillConfig(Strict):
    system_prompt: str = '依据提供的业务证据执行任务，缺少证据时说明无法确认。'
    user_template: str = '{task}'
    workflow: Literal['clarification','specification','impact','qa','ledger_fill','analysis','quality','uml','ppt_report','mind_map'] = 'qa'
    allowed_tools: list[Literal['search','read_source']] = Field(default_factory=lambda:['search','read_source'])
    base_ids: list[str] = Field(default_factory=list)
    input_schema: dict = Field(default_factory=lambda:{'type':'object','required':['task']})
    output_schema: dict = Field(default_factory=lambda:{'type':'object'})
    model_parameters: dict = Field(default_factory=lambda:{'temperature':0.2})
    human_confirmation: bool = True
    package_metadata: dict = Field(default_factory=dict)
    delivery_template: dict = Field(default_factory=dict)


class SkillInput(Strict):
    name: str = Field(min_length=1, max_length=100)
    command: str = Field(min_length=1, max_length=100)
    description: str
    public: bool = False
    config: SkillConfig = Field(default_factory=SkillConfig)


class RunInput(Strict):
    task: str = Field(min_length=1, max_length=20000)
    source_version_ids: list[str] = Field(default_factory=list)
    base_ids: list[str] = Field(default_factory=list)
    requirement_id: str | None = None
    conversation_id: str | None = None
    sample_version_ids: list[str] = Field(default_factory=list,max_length=5)
    target_system: str = Field(default='',max_length=200)
    fixed_template: bool = False
    word_template_version_id: str | None = None
    reuse_analysis: bool = True
    diagram_types: list[str] = Field(default_factory=list, max_length=15)
    report_requirement_ids: list[str] = Field(default_factory=list)
    mind_map_requirement_ids: list[str] = Field(default_factory=list)
    report_audience: str = Field(default='', max_length=200)


class ChatInput(Strict):
    content: str = Field(min_length=1, max_length=20000)
    version_ids: list[str] = Field(default_factory=list, max_length=10)
    regenerate: bool = False
    skill_id: str | None = None
    qa_mode: Literal['knowledge', 'compare', 'analysis'] = 'knowledge'
    scopes: list[Literal['formal', 'mine', 'selected']] = Field(default_factory=lambda:['formal','mine'], max_length=3)
    comparison_version_ids: list[str] = Field(default_factory=list, max_length=2)


class KnowledgeInput(Strict):
    name: str
    kind: str = 'business_rule'
    content: str
    source_version_id: str
    locator: str
    reason: str
