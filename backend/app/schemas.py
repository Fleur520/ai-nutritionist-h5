from datetime import datetime
from pydantic import BaseModel, Field
from typing import Literal

class Credentials(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=8,max_length=128)

class ProfilePatch(BaseModel):
    name: str=Field('',max_length=60)
    age: int|None=Field(None,ge=18,le=110)
    height_cm: float|None=Field(None,ge=100,le=240)
    weight_kg: float|None=Field(None,ge=20,le=350)
    goal: str=Field('balanced',pattern='^(balanced|lose|gain)$')

class MealItem(BaseModel):
    food_code: str|None=Field(None,max_length=64)
    grams: float=Field(ge=5,le=3000,allow_inf_nan=False)
    nutrition_source: Literal['catalog','model']='catalog'
    recognition_index: int|None=Field(None,ge=0,le=7)

class MealCreate(BaseModel):
    meal_type: str=Field(pattern='^(breakfast|lunch|dinner|snack)$')
    eaten_at: datetime
    image_id: str|None=None
    recognition_id: str|None=Field(None,max_length=36)
    items: list[MealItem]=Field(min_length=1,max_length=30)

class ChatMessage(BaseModel):
    message: str=Field(min_length=1,max_length=1500)
    thread_id: str=Field(min_length=1,max_length=90,pattern=r'^[\w-]+$')
