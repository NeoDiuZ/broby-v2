from datetime import datetime
from typing import Literal
from pydantic import BaseModel,Field,ConfigDict,model_validator,field_validator
class Strict(BaseModel):model_config=ConfigDict(extra='forbid')
class SourceInput(Strict):
    kind:Literal['document','audio','event','human']
    id:str=Field(min_length=1,max_length=300)
    page:int|None=Field(default=None,ge=1)
    start_ms:int|None=Field(default=None,ge=0)
    end_ms:int|None=Field(default=None,ge=0)
    text:str=Field(default='',max_length=200000)
    @model_validator(mode='after')
    def positions(self):
        if self.page is not None and self.kind!='document':raise ValueError('Page applies to documents only')
        if (self.start_ms is not None or self.end_ms is not None) and self.kind!='audio':raise ValueError('Timestamps apply to audio only')
        if self.end_ms is not None and (self.start_ms is None or self.end_ms<self.start_ms):raise ValueError('Invalid audio interval')
        return self
class Actor(Strict):
    kind:Literal['system','human']
    name:str=Field(min_length=1,max_length=300)
class Measurement(Strict):
    concept:str=Field(min_length=1,max_length=100,pattern=r'^[a-z][a-z0-9_]*$')
    name:str=Field(min_length=1,max_length=200)
    value:float=Field(allow_inf_nan=False)
    unit:str=Field(min_length=1,max_length=80)
    ref_low:float|None=Field(default=None,allow_inf_nan=False)
    ref_high:float|None=Field(default=None,allow_inf_nan=False)
    source:SourceInput|None=None
    @model_validator(mode='after')
    def interval(self):
        if self.ref_low is not None and self.ref_high is not None and self.ref_low>self.ref_high:raise ValueError('Reference minimum exceeds maximum')
        return self
class LabInput(Strict):
    patient_id:str=Field(min_length=1,max_length=200)
    dedupe_key:str=Field(min_length=1,max_length=300)
    occurred_at:datetime
    summary:str=Field(min_length=1,max_length=500)
    actor:Actor
    source:SourceInput|None=None
    body:dict=Field(default_factory=dict)
    observations:list[Measurement]=Field(default_factory=list,max_length=500)
    @field_validator('occurred_at')
    @classmethod
    def timezone_required(cls,v):
        if v.tzinfo is None:raise ValueError('occurred_at must include timezone')
        return v
class EventInput(LabInput):event_type:str=Field(min_length=1,max_length=100,pattern=r'^[a-z][a-z0-9_]*$')
