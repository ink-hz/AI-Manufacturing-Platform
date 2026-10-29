"""Bounded inline evidence and attributable component/alias history."""

from typing import Annotated

from pydantic import Field, field_serializer, model_validator

from .contracts import StrictModel
from .engineering_models import MeasurementBound
from .genealogy_models import Name, Origin


class Point(StrictModel):
    x: MeasurementBound
    y: MeasurementBound

    @field_serializer("x", "y")
    def decimal_string(self, value):
        return format(value, "f")


class Curve(StrictModel):
    name: Name
    x_unit: Name
    y_unit: Name
    points: list[Point] = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def ordered(self):
        if any(a.x >= b.x for a, b in zip(self.points, self.points[1:])):
            raise ValueError("sampling coordinates must strictly increase")
        return self


class RawEvidence(StrictModel):
    origin: Origin
    curves: list[Curve] = Field(default_factory=list, max_length=10)
    logs: list[Annotated[str, Field(max_length=4000)]] = Field(
        default_factory=list, max_length=100
    )

    @model_validator(mode="after")
    def bounded(self):
        if (
            sum(len(c.points) for c in self.curves) > 10000
            or sum(len(s) for s in self.logs) > 16000
        ):
            raise ValueError("raw evidence exceeds total bound")
        return self


class Parameter(StrictModel):
    name: Name
    value: MeasurementBound
    unit: Name

    @field_serializer("value")
    def decimal_string(self, value):
        return format(value, "f")
