from typing import Literal

from pydantic import BaseModel, Field


class BodyComposition(BaseModel):
    date: str = Field(description="date")
    age: int = Field(description="age in years")
    gender: Literal["male", "female"] = Field(description="gender")
    weight: float = Field(description="weight in kilograms")
    height: float = Field(description="height in centimeters")
    body_fat_percentage: float = Field(description="body fat percentage in percent")
    visceral_fat_rating: float = Field(description="visceral fat level in points")
    muscle_mass: float = Field(description="muscle mass in kilograms")
    bone_mass: float = Field(description="bone mass in kilograms")
    body_mass_index: float = Field(description="body mass index in kg/m^2")
    basal_metabolic_rate_kj: float = Field(description="basal metabolic rate in kJ/day")
    total_body_water: float = Field(description="total body water in liters")
    total_body_water_percentage: float = Field(description="total body water percentage")
    fat_free_mass: float = Field(description="fat free mass in kilograms")


class BodyCompositionMultipleScan(BaseModel):
    scans: list[BodyComposition] = Field(description="list of body composition scans")


class BodyCompositionTable(BodyComposition):
    name: str = Field(description="name of the person")
