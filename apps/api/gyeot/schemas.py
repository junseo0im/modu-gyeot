from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


Claim = Annotated[str, Field(min_length=1, max_length=300)]


class OCRReview(StrictModel):
    product_name: str = Field(min_length=1, max_length=200)
    claims: list[Claim] = Field(default_factory=list, max_length=3)


class Search(StrictModel):
    name: str = Field(default='', max_length=200)
    number: str = Field(default='', max_length=40)
    manufacturer: str = Field(default='', max_length=200)
    service: Literal['I0030','I1250','both'] = 'both'
    reviewed_claims: list[Claim] = Field(default_factory=list, max_length=3)

    @model_validator(mode='after')
    def identifiers(self):
        if not self.name and not self.number:
            raise ValueError('제품명 또는 품목번호를 입력해 주세요.')
        if any(ord(c) < 32 for value in (self.name,self.number,self.manufacturer) for c in value):
            raise ValueError('Invalid control characters')
        return self


class Selection(StrictModel):
    product_key: str = Field(min_length=1, max_length=100)


class OCRCorrection(StrictModel):
    corrected_text: str = Field(max_length=4000)


class Compare(StrictModel):
    product_key: str = Field(min_length=1, max_length=100)
    claims: list[str] = Field(min_length=1, max_length=3)
    consent_external: StrictBool

    @model_validator(mode='after')
    def consent_and_claims(self):
        self.claims = [c.strip() for c in self.claims]
        if not self.consent_external or any(not c or len(c)>300 for c in self.claims):
            raise ValueError('외부 전송 확인과 300자 이내 문구가 필요합니다.')
        return self